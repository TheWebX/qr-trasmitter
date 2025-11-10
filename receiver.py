import argparse
import base64
import json
import multiprocessing as mp
import os
import queue  # For the "Empty" exception
import time

from PIL import ImageGrab
from pyzbar.pyzbar import decode

from keepawake import start_mouse_keepalive

# --- Configuration ---
# This must match the sender script's chunk size
CHUNK_SIZE_BYTES = 2048
# Set how long to wait (in seconds) after the last *new* part is
# found before automatically timing out.
SCAN_TIMEOUT_SECONDS = 5
# How many screenshots to grab per second
GRAB_FPS = 20 # Increased to 20 to over-sample the 10fps broadcast
# How many parallel processes to use for decoding
# Using all available cores is a good default
NUM_DECODERS = mp.cpu_count()
# Bounding box for the screen grab. Grabbing a smaller area
# is MUCH faster. This box matches the sender's window.
# Format is (X1, Y1, X2, Y2)
# GRAB_BBOX = (0, 0, 1200, 1200) # Disabling this to scan full screen for better reliability
# ---------------------


def save_draft_and_exit(chunks, total_parts, output_filename):
    """
    Saves a draft file and a missing_parts.json.
    This is called on Ctrl+C or on timeout.
    """
    print("\n--- Saving Draft and Exiting ---")
    
    if total_parts is None or output_filename is None:
        print("No parts were received. Exiting.")
        return

    # 1. Find missing parts
    all_parts = set(range(1, total_parts + 1))
    found_parts = set(chunks.keys())
    missing_parts = sorted(list(all_parts - found_parts))

    # --- Corrected Logic Block ---
    if not missing_parts:
        # This means all parts were found, but the user interrupted
        # the script *after* the main loop finished but *before*
        # the final file was written (a very small window of time).
        print("All parts were found, but process was interrupted before final save.")
        print("The final file was not assembled. Please re-run the scanner to assemble.")
        # We don't save a draft, as all parts are in memory (but lost)
        # or the final file should have been written.
        return
    # --- End of Corrected Block ---

    print(f"Found {len(found_parts)} of {total_parts} parts.")
    print(f"Missing {len(missing_parts)} parts: {missing_parts}")

    # 2. Save the missing parts list
    remediation_data = {
        "filename": output_filename,
        "total_parts": total_parts,
        "missing": missing_parts
    }
    json_filename = "missing_parts.json"
    try:
        with open(json_filename, 'w') as f:
            json.dump(remediation_data, f, indent=2)
        print(f"Successfully saved '{json_filename}'.")
    except Exception as e:
        print(f"Error saving missing parts JSON: {e}")

    # 3. Save the DRAFT file
    draft_filename = f"DRAFT_{output_filename}"
    print(f"Saving received parts to '{draft_filename}'...")
    try:
        with open(draft_filename, 'wb') as f_out:
            # Write all chunks *in order*, filling in gaps with null bytes
            for i in range(1, total_parts + 1):
                if i in chunks:
                    # This part exists, decode and write it
                    base64_data = chunks[i]
                    binary_chunk = base64.b64decode(base64_data)
                    f_out.write(binary_chunk)
                else:
                    # This part is missing.
                    if i != total_parts:
                        # Write null bytes for the full chunk size
                        f_out.write(b'\0' * CHUNK_SIZE_BYTES)
                            
        print(f"Successfully saved draft file.")
        print("\nTo resume, run the SENDER with the --remediate flag:")
        print(f"python show_qr_series.py {output_filename} --remediate {json_filename}")
        print("Then, re-run this scanner script to capture the missing parts.")

    except Exception as e:
        print(f"Error saving draft file: {e}")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Receive QR code broadcasts and reconstruct the original file."
    )
    parser.add_argument(
        "--keep-awake",
        action="store_true",
        help="Simulate a mouse click every 5 minutes to prevent the receiver screen from turning off."
    )
    return parser.parse_args()


# --- Worker Processes ---

def grabber_process(frame_queue):
    """
    Grabs screenshots at the target FPS and puts them in a queue.
    This runs in its own process.
    """
    while True:
        try:
            # img = ImageGrab.grab(bbox=GRAB_BBOX) # Changed to full screen grab
            img = ImageGrab.grab()
            
            try:
                # Put in the queue, but don't wait forever
                frame_queue.put(img, timeout=0.5) 
            except queue.Full:
                # This is the problem: decoders are not keeping up!
                print("[WARNING] Grabber: Frame queue is full. Decoders are too slow. Dropping frame.")
                pass # Drop the frame and keep grabbing
            
            time.sleep(1.0 / GRAB_FPS)
        except Exception as e:
            # Handle cases where screen grab fails (e.g., screen locked)
            print(f"Grabber error: {e}")
            time.sleep(1)

def decoder_process(frame_queue, result_queue):
    """
    Pulls images from the frame_queue, decodes them,
    and puts results in the result_queue.
    This runs in a pool of parallel processes.
    """
    # This redirects stderr to os.devnull *within this worker process*
    # to suppress C-level warnings from zbar.
    import sys
    sys.stderr = open(os.devnull, 'w')
    
    while True:
        try:
            img = frame_queue.get()
            decoded_objects = decode(img)
            
            if decoded_objects:
                # Put the raw byte data into the result queue
                result_queue.put(decoded_objects[0].data)
        except Exception as e:
            # A single decode error shouldn't crash a worker
            # print(f"Decoder error: {e}")
            pass

# --- Main Controller ---

def main_scanner(keep_awake: bool = False):
    """
    Main process. Manages the worker processes and
    assembles the final file from the results queue.
    """
    
    print("--- High-Performance Scanner Started ---")
    print(f"Using {NUM_DECODERS} parallel decoder processes.")
    print("Press Ctrl+C to stop scanning and save a draft.")
    print("Waiting for the first part...")

    # Queues for process communication
    # maxsize helps prevent runaway memory use
    frame_queue = mp.Queue(maxsize=1000)  # Increased buffer
    result_queue = mp.Queue(maxsize=1000)  # Increased buffer
    
    processes = []
    stop_keepalive = None
    if keep_awake:
        stop_keepalive = start_mouse_keepalive()
        if stop_keepalive is None:
            print("Keep-awake feature requested but could not be started.")
    
    chunks = {}
    total_parts = None
    output_filename = None
    last_part_found_time = time.time()
    
    try:
        # 1. Start the Grabber Process
        grabber = mp.Process(target=grabber_process, args=(frame_queue,))
        grabber.daemon = True
        grabber.start()
        processes.append(grabber)
        
        # 2. Start the Decoder Process Pool
        for _ in range(NUM_DECODERS):
            decoder = mp.Process(target=decoder_process, args=(frame_queue, result_queue))
            decoder.daemon = True
            decoder.start()
            processes.append(decoder)

        # 3. This is the main loop for processing results
        while True:
            # Check for timeout first
            if total_parts is not None:
                time_since_last_part = time.time() - last_part_found_time
                if len(chunks) < total_parts and time_since_last_part > SCAN_TIMEOUT_SECONDS:
                    print(f"\nScan timed out (no new parts found in {SCAN_TIMEOUT_SECONDS} seconds).")
                    print("Assuming broadcast is complete.")
                    raise KeyboardInterrupt # Trigger the cleanup/save
            
            try:
                # Check for a result from the decoder pool
                # Use a short timeout to keep the loop responsive
                qr_data_string = result_queue.get(timeout=0.05).decode('utf-8')
                
                # Try to parse the result
                try:
                    payload = json.loads(qr_data_string)
                    part_num = payload['p']
                    base64_data = payload['d']
                    
                    if part_num not in chunks:
                        if total_parts is None:
                            total_parts = payload['t']
                            output_filename = payload['f']
                            print("\n--- Found First Part! ---")
                            print(f"Target file: {output_filename}")
                            print(f"Total parts to find: {total_parts}")
                            
                            # Check for/load draft file
                            draft_file = f"DRAFT_{output_filename}"
                            if os.path.exists(draft_file):
                                print(f"Resuming from existing '{draft_file}'.")
                                print("Loading existing parts from draft...")
                                try:
                                    with open(draft_file, 'rb') as f_in:
                                        for i in range(1, total_parts + 1):
                                            chunk = f_in.read(CHUNK_SIZE_BYTES)
                                            if not chunk: break
                                            if chunk != (b'\0' * CHUNK_SIZE_BYTES) and chunk != (b'\0' * len(chunk)):
                                                if i not in chunks:
                                                    chunks[i] = base64.b64encode(chunk).decode('utf-8')
                                    print(f"Loaded {len(chunks)} existing parts.")
                                except Exception as e:
                                    print(f"Error reading draft file: {e}")

                        # A new part was found! Reset the timeout timer.
                        last_part_found_time = time.time()
                        chunks[part_num] = base64_data
                        print(f"Captured part {part_num}/{total_parts}. Progress: [{len(chunks)} of {total_parts}]")

                except (json.JSONDecodeError, KeyError, TypeError):
                    print("Found an unrelated QR code. Ignoring...")

            except queue.Empty:
                # This is normal, means no QR was decoded in the last 50ms
                # Just loop again
                time.sleep(0.01) # Small sleep to prevent busy-looping
                continue

            # Check for completion
            if total_parts is not None and len(chunks) == total_parts:
                print("\n--- All Parts Found! ---")
                print("Reassembling file...")
                
                restored_filename = f"RESTORED_{output_filename}"
                
                try:
                    with open(restored_filename, 'wb') as f_out:
                        for i in range(1, total_parts + 1):
                            f_out.write(base64.b64decode(chunks[i]))
                            
                    print(f"\nSUCCESS! File reassembled as '{restored_filename}'.")
                    
                    # Clean up draft files
                    draft_file = f"DRAFT_{output_filename}"
                    json_file = "missing_parts.json"
                    if os.path.exists(draft_file): os.remove(draft_file)
                    if os.path.exists(json_file): os.remove(json_file)
                        
                    break # Exit the main while loop

                except Exception as e:
                    print(f"FATAL ERROR: Could not write file. {e}")
                    break

    except KeyboardInterrupt:
        # User pressed Ctrl+C
        save_draft_and_exit(chunks, total_parts, output_filename)

    finally:
        # Clean up all worker processes
        print("\nStopping worker processes...")
        for p in processes:
            p.terminate()
            p.join()
        if stop_keepalive:
            stop_keepalive()
        print("Script terminated.")

if __name__ == "__main__":
    args = parse_args()
    # This is crucial for multiprocessing on Windows
    mp.freeze_support()
    main_scanner(keep_awake=args.keep_awake)

