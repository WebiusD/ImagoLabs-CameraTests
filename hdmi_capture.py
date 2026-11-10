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
from framing import JpegBuffer, crop_to_aspect, detect_content_aspect, encode_jpeg

log = logging.getLogger(__name__)

CONTENT_DETECT_INTERVAL_S = 1.0


class HdmiCapture:
    def __init__(self, device: int = config.HDMI_DEVICE):
        self.device = device
        self.cap: Optional[cv2.VideoCapture] = None

        self.buffer = JpegBuffer()
        self.content_aspect: Optional[float] = config.HDMI_CONTENT_ASPECT
        self._content_checked_at = 0.0
        self._running = True
        self._streaming = threading.Event()

        self.frames_received = 0
        self.last_frame_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.opened_at: Optional[float] = None
        self.actual_width = 0
        self.actual_height = 0
        self.requested_fps = 0.0

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
            if index == self.device and self.cap is not None:
                # Already open here, so a second open would fail.
                found.append(
                    {"index": index, "width": self.actual_width, "height": self.actual_height}
                )
                continue
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

        # FOURCC must be set before size/fps: these cards only offer 1080p at
        # 30+ fps as MJPEG (YUYV tops out at 10 fps).
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, config.HDMI_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Hand out the raw MJPEG bytes: OpenCV's internal V4L2 decode only
        # manages ~15 fps at 1080p, cv2.imdecode is several times faster.
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

        self.cap = cap
        self.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.requested_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        self.buffer.clear()
        self.content_aspect = config.HDMI_CONTENT_ASPECT
        self._content_checked_at = 0.0
        self.frames_received = 0
        self.last_frame_at = None
        self.last_error = None
        self.opened_at = time.time()
        self._streaming.set()

        log.info(
            "HDMI capture started on device %s (%sx%s @ %s fps)",
            self.device,
            self.actual_width,
            self.actual_height,
            self.requested_fps,
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

        self.buffer.clear()

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
            if ok and frame is not None and frame.ndim < 3:
                frame = cv2.imdecode(frame.reshape(-1), cv2.IMREAD_COLOR)
            if not ok or frame is None:
                self.last_error = "Frame read failed (no HDMI signal?)"
                time.sleep(0.05)
                continue

            now = time.time()
            if (
                config.HDMI_CONTENT_ASPECT is None
                and now - self._content_checked_at >= CONTENT_DETECT_INTERVAL_S
            ):
                self.content_aspect = detect_content_aspect(frame)
                self._content_checked_at = now

            cropped = crop_to_aspect(frame, config.PREVIEW_ASPECT, self.content_aspect)
            jpeg = encode_jpeg(cropped, config.JPEG_QUALITY)
            if jpeg is not None:
                self.buffer.put(jpeg, cropped.shape[1], cropped.shape[0])

            self.frames_received += 1
            self.last_frame_at = now
            self.last_error = None

    def get_jpeg(self) -> Optional[bytes]:
        return self.buffer.latest()

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
            "requested_fps": self.requested_fps,
            "fps": round(self.buffer.fps, 1) if alive else 0.0,
            "output_width": self.buffer.width,
            "output_height": self.buffer.height,
            "content_aspect": None if self.content_aspect is None else round(self.content_aspect, 3),
            "error": self.last_error,
            "opened_at": self.opened_at,
        }
