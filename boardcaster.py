import base64
import json
import os
import math
import sys
import tkinter as tk
from PIL import Image, ImageTk
import threading
import argparse
import queue
import time
import qrcode

from keepawake import start_mouse_keepalive

# --- Configuration ---
# Set the size of the data chunk (in bytes)
# This *must* match the receiver script
CHUNK_SIZE_BYTES = 2048
# ---------------------

def get_file_chunks(file_path):
    """Reads a file and yields binary chunks of it."""
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                yield chunk
    except FileNotFoundError:
        print(f"Error: Source file '{file_path}' not found.")
        return None
    except Exception as e:
        print(f"Error reading file '{file_path}': {e}")
        return None

def generate_qr_image(data, box_size=6):
    """Generates a single QR code image in memory."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=box_size,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

class QRPresenter:
    """
    A Tkinter GUI class to display images from a queue.
    """
    def __init__(self, root, image_queue, total_parts, resolution="1200x1200"):
        self.root = root
        self.image_queue = image_queue
        self.total_parts = total_parts
        self.current_part = 0
        
        self.root.title("QR Code Broadcaster")
        
        # Set window size and position
        try:
            self.root.geometry(f"{resolution}+0+0")
        except Exception:
             print(f"Warning: Invalid resolution '{resolution}'. Defaulting to 1200x1200.")
             self.root.geometry("1200x1200+0+0")
        
        self.root.resizable(False, False)
        self.root.configure(bg='black')

        self.label = tk.Label(root, bg='black')
        self.label.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.check_for_image()

    def check_for_image(self):
        """
        Checks the queue for a new image, resizes it to fit, and displays it.
        """
        try:
            # Get an image from the queue (non-blocking)
            img = self.image_queue.get_nowait()
            
            if img is None:
                self.show_end_message()
                return

            # --- Resizing Logic ---
            # Get current available display dimensions
            w = self.label.winfo_width()
            h = self.label.winfo_height()

            # Only resize if the window has initialized its size (w > 1)
            if w > 1 and h > 1:
                # QR codes are square. Find the smallest dimension to fit it in.
                min_dim = min(w, h)
                # Resize the PIL image, keeping a small margin
                # Use LANCZOS for high-quality downsampling
                try:
                    resample_mode = Image.Resampling.LANCZOS
                except AttributeError:
                    # Fallback for older Pillow versions
                    resample_mode = Image.LANCZOS
                    
                img = img.resize((min_dim, min_dim), resample_mode)
            # ----------------------

            # Convert to PhotoImage and display
            self.photo = ImageTk.PhotoImage(img)
            self.label.config(image=self.photo)
            
            self.current_part += 1
            self.root.title(f"QR Code Broadcaster - Part {self.current_part}/{self.total_parts}")

            self.root.after(100, self.check_for_image)

        except queue.Empty:
            self.root.after(10, self.check_for_image)

    def show_end_message(self):
        """Displays a 'Finished' message."""
        self.label.config(image=None, text="All parts sent.", font=("Arial", 30), fg="white")
        self.root.title("QR Code Broadcaster - Finished")

def generation_thread(file_path, remediation_parts, image_queue):
    """
    Generates QR codes and puts them into the queue.
    """
    try:
        file_size = os.path.getsize(file_path)
        total_parts = math.ceil(file_size / CHUNK_SIZE_BYTES)
        
        print(f"Total parts to generate: {total_parts}")
        file_name = os.path.basename(file_path)

        for part_number, chunk_data in enumerate(get_file_chunks(file_path), 1):
            if remediation_parts and part_number not in remediation_parts:
                continue
            
            print(f"  > Broadcasting part {part_number}/{total_parts}")

            base64_data = base64.b64encode(chunk_data).decode('utf-8')
            payload = {
                "p": part_number,
                "t": total_parts,
                "f": file_name,
                "d": base64_data
            }
            json_string = json.dumps(payload)
            
            # Generate high-res QR initially; GUI will downscale it to fit.
            img = generate_qr_image(json_string, box_size=10)
            
            image_queue.put(img)

        image_queue.put(None)

    except Exception as e:
        print(f"Error in generation thread: {e}")
        image_queue.put(None)

def main():
    parser = argparse.ArgumentParser(description="Broadcast a file as a series of QR codes.")
    parser.add_argument("file", help="The path to the file you want to send.")
    parser.add_argument("--remediate", help="Path to a 'missing_parts.json' file for remediation.")
    parser.add_argument("--resolution", default="1200x1200", help="Window resolution (e.g., 1200x700). Default is 1200x1200.")
    parser.add_argument(
        "--keep-awake",
        action="store_true",
        help="Simulate a mouse click every 5 minutes to prevent the broadcaster screen from turning off."
    )
    
    args = parser.parse_args()

    remediation_parts = None
    if args.remediate:
        try:
            with open(args.remediate, 'r') as f:
                remediation_data = json.load(f)
                remediation_parts = set(remediation_data.get("missing", []))
            if not remediation_parts:
                print("Error: Remediation file is empty or invalid.")
                return
            print(f"--- REMEDIATION MODE ---")
            print(f"Only sending {len(remediation_parts)} missing parts: {sorted(list(remediation_parts))}")
        except Exception as e:
             print(f"Error loading remediation file: {e}")
             return

    if not os.path.exists(args.file):
        print(f"Error: Source file '{args.file}' not found.")
        return

    image_queue = queue.Queue(maxsize=1)
    file_size = os.path.getsize(args.file)
    total_parts = math.ceil(file_size / CHUNK_SIZE_BYTES)
    display_total = len(remediation_parts) if remediation_parts else total_parts

    stop_keepalive = None
    if args.keep_awake:
        stop_keepalive = start_mouse_keepalive()
        if stop_keepalive is None:
            print("Keep-awake feature requested but could not be started.")

    root = tk.Tk()
    app = QRPresenter(root, image_queue, display_total, args.resolution)

    gen_thread = threading.Thread(
        target=generation_thread,
        args=(args.file, remediation_parts, image_queue),
        daemon=True
    )
    gen_thread.start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nBroadcast stopped by user.")
    finally:
        if stop_keepalive:
            stop_keepalive()
        print("Closing application.")

if __name__ == "__main__":
    main()