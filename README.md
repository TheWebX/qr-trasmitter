Here is a comprehensive `README.md` for your optical file transfer tools.

-----

# Optical QR Code File Transfer Tools

This project contains two Python scripts designed to transfer files between computers without a network connection (air-gapped), using a sequence of QR codes displayed on one screen and captured by another.

  * **Sender (`boardcaster.py`):** Breaks a file into binary chunks, encodes them into a stream of QR codes, and displays them in a configurable window.
  * **Receiver (`receiver.py`):** High-performance screen scanner that detects these QR codes, decodes the data, and reassembles the original file.

## Prerequisites

Both scripts require **Python 3**. You will need to install specific dependencies for each script.

### Common Dependencies

```bash
pip install pillow
```

### Sender Dependencies

```bash
pip install qrcode[pil]
```

*(Note: Tkinter is also required, which usually comes standard with Python installations. If missing on Linux, install `python3-tk`)*

### Receiver Dependencies

```bash
pip install pyzbar
```

*(Note: `pyzbar` requires the ZBar shared library to be installed on your system. On Windows, the pip package usually includes it. On Linux, you may need `sudo apt-get install libzbar0`)*

-----

## Standard Workflow

### 1\. Start the Receiver

On the destination computer, run the receiver script first. It will begin scanning the screen immediately, waiting for QR codes to appear.

```bash
python receiver.py
```

*It will display "Waiting for the first part..."*

### 2\. Start the Broadcaster (Sender)

On the source computer, start broadcasting your target file.

```bash
python boardcaster.py ConfidentialDocument.pdf
```

The broadcaster will open a window displaying the QR codes.
**Ensure this window is visible on the Receiver's screen** (e.g., if using a video capture card, standard remote desktop, or if running both on the same machine for testing).

### 3\. Transfer & Completion

  * The **Receiver** will automatically detect the first QR code, learn the filename and total number of parts, and begin capturing.
  * Once all parts are collected, the Receiver will automatically reassemble them into `RESTORED_[OriginalName.ext]` and terminate.
  * The **Sender** will show a "Finished" message when it has cycled through all parts once.

-----

## Advanced Usage

### Sender Options (`boardcaster.py`)

**Setting Window Resolution:**
You can adjust the broadcaster window size to fit your display setup using the `--resolution` flag.

```bash
python boardcaster.py large_file.zip --resolution 1280x720
```

### Receiver Features (`receiver.py`)

**Drafts & Resuming:**
If the transfer is interrupted (Ctrl+C) or times out (default 5 seconds of no new data), the Receiver will:

1.  Save all currently received parts into a `DRAFT_filename` file.
2.  Generate a `missing_parts.json` file listing exactly which chunks failed to transfer.

If you run `receiver.py` again and a matching `DRAFT_` file exists, it will automatically load it and only look for the missing parts.

-----

## Remediation Mode (Fixing dropped packets)

If a transfer finishes but is missing parts (due to screen lag, focus issues, etc.), you don't have to start over.

1.  On the **Receiver** side, let it timeout or press Ctrl+C. It will generate `missing_parts.json`.
2.  Transfer this small JSON file back to the **Sender** computer (e.g., manually typing the numbers if truly air-gapped, or via USB).
3.  Run the **Sender** in remediation mode:
    ```bash
    python boardcaster.py ConfidentialDocument.pdf --remediate missing_parts.json
    ```
    *The sender will now ONLY cycle through the specifically missed parts.*
4.  Run the **Receiver** again. It will load its draft and quickly catch
