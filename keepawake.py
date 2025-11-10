import threading
from typing import Callable, Optional

DEFAULT_INTERVAL_SECONDS = 300


def start_mouse_keepalive(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> Optional[Callable[[], None]]:
    """
    Starts a background thread that simulates a mouse click at regular intervals.

    Returns a callable that stops the thread when invoked. If the optional
    dependency 'pyautogui' is not available, the function returns None and
    prints a warning.
    """
    try:
        import pyautogui
    except ImportError:
        print("Warning: 'pyautogui' is not installed. Mouse keep-alive is unavailable.")
        print("Install it with 'pip install pyautogui' to enable this feature.")
        return None

    stop_event = threading.Event()

    def worker():
        print(f"Mouse keep-alive enabled. Simulating a click every {interval_seconds} seconds.")
        while not stop_event.wait(interval_seconds):
            try:
                pyautogui.click()
            except Exception as exc:
                print(f"Mouse keep-alive encountered an error: {exc}")
                break

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def stop():
        stop_event.set()

    return stop
