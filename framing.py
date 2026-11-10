"""Crop helpers so previews fill a 16:9 screen without black bars."""

from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np

# Narrowest first: the narrowest aspect whose side bars are black wins, because
# a 3:2 picture also has black where 16:9 would put image, but not where 4:3 bars sit.
_CANDIDATE_ASPECTS = (4 / 3, 3 / 2)
_BLACK_MAX = 40


def detect_content_aspect(frame: np.ndarray) -> float:
    """Aspect ratio of the picture inside a pillarboxed HDMI frame."""
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame[::4, ::4], cv2.COLOR_BGR2GRAY)
    for aspect in _CANDIDATE_ASPECTS:
        bar = int((width - height * aspect) / 2) // 4
        if bar <= 2:
            continue
        if gray[:, :bar].max() < _BLACK_MAX and gray[:, -bar:].max() < _BLACK_MAX:
            return aspect
    return width / height


def crop_to_aspect(
    frame: np.ndarray,
    target_aspect: Optional[float],
    content_aspect: Optional[float] = None,
) -> np.ndarray:
    """Drop pillarbox bars, then centre-crop the picture to ``target_aspect``."""
    height, width = frame.shape[:2]

    if content_aspect is not None:
        content_w = min(width, int(round(height * content_aspect)))
        x0 = (width - content_w) // 2
        frame = frame[:, x0 : x0 + content_w]
        height, width = frame.shape[:2]

    if not target_aspect:
        return frame

    if width / height > target_aspect:
        new_w = int(round(height * target_aspect))
        x0 = (width - new_w) // 2
        return frame[:, x0 : x0 + new_w]

    new_h = int(round(width / target_aspect))
    y0 = (height - new_h) // 2
    return frame[y0 : y0 + new_h, :]


class JpegBuffer:
    """Latest encoded frame plus a measured frame rate, shared with MJPEG clients."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._jpeg: Optional[bytes] = None
        self._seq = 0
        self._window_start = time.time()
        self._window_frames = 0
        self.fps = 0.0
        self.width = 0
        self.height = 0

    def put(self, jpeg: bytes, width: int, height: int) -> None:
        now = time.time()
        with self._cond:
            self._jpeg = jpeg
            self._seq += 1
            self.width, self.height = width, height
            self._window_frames += 1
            if now - self._window_start >= 1.0:
                self.fps = self._window_frames / (now - self._window_start)
                self._window_start = now
                self._window_frames = 0
            self._cond.notify_all()

    def clear(self) -> None:
        with self._cond:
            self._jpeg = None
            self.fps = 0.0
            self._window_start = time.time()
            self._window_frames = 0

    def latest(self) -> Optional[bytes]:
        with self._cond:
            return self._jpeg

    def wait_newer(self, seq: int, timeout: float = 1.0) -> tuple[Optional[bytes], int]:
        """Block until a frame newer than ``seq`` exists; returns (jpeg, seq)."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq != seq, timeout=timeout)
            if self._seq == seq:
                return None, seq
            return self._jpeg, self._seq


def encode_jpeg(frame: np.ndarray, quality: int) -> Optional[bytes]:
    ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return jpeg.tobytes() if ok else None
