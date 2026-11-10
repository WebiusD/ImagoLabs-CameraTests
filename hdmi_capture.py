"""HDMI capture-card reader (OpenCV / V4L2).

Adapted from ImagoLabs-DreamMachine ``ai_photobox/services/camera.py``:
a background thread keeps the latest frame, and MJPEG bytes are served to the
web UI. Uses V4L2 on Linux instead of DirectShow.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2

import config

log = logging.getLogger(__name__)


class HdmiCapture:
    def __init__(self, device: int = config.HDMI_DEVICE):
        self.device = device
        self.cap: Optional[cv2.VideoCapture] = None

        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._streaming = threading.Event()

        self.frames_received = 0
        self.last_frame_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.opened_at: Optional[float] = None
        self.actual_width = 0
        self.actual_height = 0

        threading.Thread(
            target=self._loop,
            daemon=True,
            name="HdmiCaptureLoop",
        ).start()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def list_devices(self, max_index: int = 10) -> list[dict]:
        """Probe ``/dev/videoN`` indices that OpenCV can open."""
        found = []
        for index in range(max_index):
            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                found.append({"index": index, "width": width, "height": height})
                cap.release()
        return found

    def start(self, device: Optional[int] = None) -> dict:
        if device is not None:
            self.device = device

        self.stop()
        time.sleep(0.3)

        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            # Fallback without forcing V4L2 (useful for some USB grabbers).
            cap = cv2.VideoCapture(self.device)

        if not cap.isOpened():
            self.last_error = f"Could not open video device {self.device}"
            raise RuntimeError(self.last_error)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        # Prefer MJPEG from UVC capture cards when available.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        self.cap = cap
        self.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.frames_received = 0
        self.last_frame_at = None
        self.last_error = None
        self.opened_at = time.time()
        self._streaming.set()

        log.info(
            "HDMI capture started on device %s (%sx%s)",
            self.device,
            self.actual_width,
            self.actual_height,
        )
        return self.status()

    def stop(self) -> dict:
        self._streaming.clear()
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                log.exception("Error releasing capture device")
            self.cap = None

        with self._lock:
            self._frame = None

        log.info("HDMI capture stopped")
        return self.status()

    def restart(self) -> dict:
        """Re-open the same device — useful after photo capture interrupts HDMI."""
        device = self.device
        return self.start(device)

    def shutdown(self) -> None:
        self._running = False
        self.stop()

    # ------------------------------------------------------------------
    # Frame loop / consumers
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while self._running:
            if not self._streaming.is_set() or self.cap is None:
                time.sleep(0.05)
                continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.last_error = "Frame read failed (no HDMI signal?)"
                time.sleep(0.05)
                continue

            with self._lock:
                self._frame = frame
            self.frames_received += 1
            self.last_frame_at = time.time()
            self.last_error = None
            time.sleep(0.001)

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()

        if frame is None:
            return None

        ok, jpeg = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), config.JPEG_QUALITY],
        )
        return jpeg.tobytes() if ok else None

    def status(self) -> dict:
        now = time.time()
        age = None if self.last_frame_at is None else now - self.last_frame_at
        streaming = self._streaming.is_set() and self.cap is not None
        alive = age is not None and age < config.FRAME_STALE_SECONDS

        if not streaming:
            state = "stopped"
        elif alive:
            state = "streaming"
        elif self.frames_received == 0:
            state = "no_signal"
        else:
            state = "stale"

        return {
            "state": state,
            "device": self.device,
            "streaming": streaming,
            "alive": alive,
            "frames_received": self.frames_received,
            "last_frame_age_s": None if age is None else round(age, 3),
            "width": self.actual_width,
            "height": self.actual_height,
            "error": self.last_error,
            "opened_at": self.opened_at,
        }
