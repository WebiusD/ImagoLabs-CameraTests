"""gphoto2 USB live view (capture_preview) for comparison with the HDMI feed."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import gphoto2 as gp
import numpy as np

import config
from framing import JpegBuffer, crop_to_aspect, encode_jpeg
from gphoto_control import GphotoControl

log = logging.getLogger(__name__)


class UsbLiveView:
    def __init__(self, camera: GphotoControl):
        self.camera = camera
        self.buffer = JpegBuffer()
        self._enabled = threading.Event()
        self._running = True

        self.frames_received = 0
        self.last_frame_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.source_width = 0
        self.source_height = 0

        threading.Thread(target=self._loop, daemon=True, name="UsbLiveView").start()

    def start(self) -> dict:
        if not self.camera.connected:
            raise RuntimeError("Connect the camera over USB first")
        self.frames_received = 0
        self.last_frame_at = None
        self.last_error = None
        self.buffer.clear()
        if self.camera.is_canon_eos:
            # Live view normally goes to "PC" only, which switches HDMI off.
            # Asking for both before the first preview keeps HDMI running.
            self.camera.set_evf_output("TFT + PC")
        self._enabled.set()
        log.info("USB live view started")
        return self.status()

    def stop(self) -> dict:
        self._enabled.clear()
        self.buffer.clear()
        output_restored = self.camera.is_canon_eos and self.camera.set_evf_output("TFT")
        if self.camera.connected and not output_restored:
            # Opening a fresh session also hands live view back to the camera.
            try:
                self.camera.reconnect()
            except Exception as exc:
                self.last_error = f"Reconnect after live view failed: {exc}"
                log.warning(self.last_error)
        log.info("USB live view stopped")
        return self.status()

    def shutdown(self) -> None:
        self._running = False
        self._enabled.clear()

    def _grab(self) -> Optional[bytes]:
        with self.camera._cam_lock:
            if self.camera.camera is None:
                return None
            if not self._enabled.is_set():
                return b""
            preview = self.camera.camera.capture_preview()
            return bytes(preview.get_data_and_size())

    def _loop(self) -> None:
        while self._running:
            if not self._enabled.is_set():
                time.sleep(0.05)
                continue

            try:
                data = self._grab()
            except gp.GPhoto2Error as exc:
                # Busy (e.g. during a still capture) or live view not allowed.
                self.last_error = str(exc)
                time.sleep(0.2)
                continue

            if data is None:
                self.last_error = "Camera not connected"
                time.sleep(0.2)
                continue
            if not data:
                continue

            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                self.last_error = "Could not decode preview frame"
                continue

            self.source_height, self.source_width = frame.shape[:2]
            cropped = crop_to_aspect(frame, config.PREVIEW_ASPECT)
            jpeg = encode_jpeg(cropped, config.JPEG_QUALITY)
            if jpeg is not None:
                self.buffer.put(jpeg, cropped.shape[1], cropped.shape[0])

            self.frames_received += 1
            self.last_frame_at = time.time()
            self.last_error = None
            # Let a waiting still capture grab the camera lock between frames.
            time.sleep(0.005)

    def status(self) -> dict:
        enabled = self._enabled.is_set()
        age = None if self.last_frame_at is None else time.time() - self.last_frame_at
        alive = age is not None and age < config.USB_PREVIEW_STALE_SECONDS

        if not enabled:
            state = "stopped"
        elif alive:
            state = "streaming"
        elif self.frames_received == 0:
            state = "starting"
        else:
            state = "stale"

        return {
            "state": state,
            "enabled": enabled,
            "alive": alive,
            "frames_received": self.frames_received,
            "last_frame_age_s": None if age is None else round(age, 3),
            "fps": round(self.buffer.fps, 1) if alive else 0.0,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "output_width": self.buffer.width,
            "output_height": self.buffer.height,
            "error": self.last_error,
        }
