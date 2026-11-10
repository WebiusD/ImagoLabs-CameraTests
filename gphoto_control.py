"""gphoto2 camera control with capability probing.

Adapted from ImagoLabs-DreamMachine ``ai_photobox/services/nikon.py``:
one persistent libgphoto2 session, serialised with a lock, and single-config
reads/writes instead of full-tree get_config (much faster).
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import gphoto2 as gp

import config

log = logging.getLogger(__name__)

GP_ERROR_IO_USB_CLAIM = -53


class GphotoControl:
    def __init__(self, capture_dir: Path = config.CAPTURE_DIR):
        self.capture_dir = Path(capture_dir)
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self.camera: Optional[gp.Camera] = None
        self._cam_lock = threading.RLock()
        self.connected = False
        self.model: Optional[str] = None
        self.last_error: Optional[str] = None
        self.connected_at: Optional[float] = None
        self.capabilities: dict[str, Any] = {}
        self.last_capture: Optional[dict] = None

    # ------------------------------------------------------------------
    # USB claim helpers
    # ------------------------------------------------------------------
    @staticmethod
    def release_desktop_claims() -> None:
        """Best-effort kill of gvfs processes that auto-claim PTP cameras."""
        for pattern in ("gvfs-gphoto2-volume-monitor", "gvfsd-gphoto2"):
            subprocess.run(
                ["pkill", "-f", pattern],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(0.4)

    @staticmethod
    def _close_quietly(camera: gp.Camera) -> None:
        try:
            camera.exit()
        except Exception:
            pass

    def _open_camera(self) -> gp.Camera:
        camera = gp.Camera()
        try:
            camera.init()
        except Exception:
            self._close_quietly(camera)
            raise
        return camera

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------
    def connect(self, release_claims: bool = True) -> dict:
        with self._cam_lock:
            if self.camera is not None:
                return self.status()

            if release_claims:
                self.release_desktop_claims()

            try:
                self.camera = self._open_camera()
            except gp.GPhoto2Error as exc:
                if getattr(exc, "code", None) == GP_ERROR_IO_USB_CLAIM:
                    self.release_desktop_claims()
                    try:
                        self.camera = self._open_camera()
                    except Exception as retry_exc:
                        self.last_error = str(retry_exc)
                        self.connected = False
                        raise
                else:
                    self.last_error = str(exc)
                    self.connected = False
                    raise

            self.connected = True
            self.connected_at = time.time()
            self.last_error = None
            self.model = self._read_model()
            self.capabilities = self.probe_capabilities()
            log.info("gphoto2 connected: %s", self.model)
            return self.status()

    def disconnect(self) -> dict:
        with self._cam_lock:
            if self.camera is not None:
                self._close_quietly(self.camera)
                self.camera = None
            self.connected = False
            self.model = None
            self.capabilities = {}
            self.connected_at = None
            log.info("gphoto2 disconnected")
            return self.status()

    def _read_model(self) -> str:
        try:
            summary = self.camera.get_summary().text  # type: ignore[union-attr]
            for line in summary.splitlines():
                if "Model" in line:
                    return line.split(":", 1)[-1].strip()
            return summary.splitlines()[0] if summary else "unknown"
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------
    # Capability probing
    # ------------------------------------------------------------------
    def _list_config_names(self) -> set[str]:
        names: set[str] = set()
        if self.camera is None:
            return names

        def walk(widget: gp.CameraWidget) -> None:
            try:
                name = widget.get_name()
                if name:
                    names.add(name)
            except Exception:
                pass
            try:
                count = widget.count_children()
            except Exception:
                return
            for i in range(count):
                try:
                    walk(widget.get_child(i))
                except Exception:
                    continue

        try:
            walk(self.camera.get_config())
        except gp.GPhoto2Error as exc:
            log.warning("Could not list full config tree: %s", exc)
        return names

    def _widget_choices(self, name: str) -> Optional[dict]:
        try:
            widget = self.camera.get_single_config(name)  # type: ignore[union-attr]
            wtype = widget.get_type()
            current = widget.get_value()
            choices = []
            if wtype in (gp.GP_WIDGET_MENU, gp.GP_WIDGET_RADIO):
                for i in range(widget.count_choices()):
                    choices.append(widget.get_choice(i))
            return {
                "name": name,
                "type": int(wtype),
                "current": current if not isinstance(current, bytes) else current.decode(),
                "choices": choices,
                "readonly": bool(widget.get_readonly()),
            }
        except gp.GPhoto2Error:
            return None

    def probe_capabilities(self) -> dict[str, Any]:
        """Discover which exposure / zoom / AF widgets this body exposes."""
        with self._cam_lock:
            if self.camera is None:
                return {}

            available = self._list_config_names()
            exposure: dict[str, Any] = {}
            for name in config.EXPOSURE_SETTINGS:
                if name in available:
                    info = self._widget_choices(name)
                    if info is not None:
                        exposure[name] = info

            actions: dict[str, Any] = {}
            for label, candidates in config.ACTION_SETTINGS:
                matched = None
                for candidate in candidates:
                    if candidate in available:
                        info = self._widget_choices(candidate)
                        if info is not None:
                            matched = info
                            break
                actions[label] = {
                    "supported": matched is not None,
                    "config": matched,
                }

            return {
                "all_config_count": len(available),
                "exposure": exposure,
                "actions": actions,
            }

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def get_setting(self, name: str) -> dict:
        with self._cam_lock:
            if self.camera is None:
                raise RuntimeError("Camera not connected")
            info = self._widget_choices(name)
            if info is None:
                raise RuntimeError(f"Setting '{name}' is not available")
            return info

    def set_setting(self, name: str, value: Any) -> dict:
        with self._cam_lock:
            if self.camera is None:
                raise RuntimeError("Camera not connected")
            try:
                widget = self.camera.get_single_config(name)
                # Coerce to int when the widget expects a number.
                current = widget.get_value()
                if isinstance(current, int) and not isinstance(value, int):
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        pass
                widget.set_value(value)
                self.camera.set_single_config(name, widget)
                self.last_error = None
                return self._widget_choices(name) or {"name": name, "current": value}
            except gp.GPhoto2Error as exc:
                self.last_error = str(exc)
                raise RuntimeError(f"Could not set {name}={value}: {exc}") from exc

    def trigger_action(self, label: str) -> dict:
        """Fire autofocus / zoom-style actions when the camera supports them."""
        caps = self.capabilities.get("actions", {}).get(label)
        if not caps or not caps.get("supported"):
            raise RuntimeError(f"Action '{label}' is not supported on this camera")

        cfg = caps["config"]
        name = cfg["name"]
        choices = cfg.get("choices") or []

        # Autofocus drive widgets usually want 0/1 or "1".
        if label == "autofocus":
            value: Any = 1
            if choices:
                value = "1" if "1" in choices else choices[-1]
            return self.set_setting(name, value)

        if label == "viewfinder":
            current = cfg.get("current")
            if current in (1, "1", True):
                value = 0 if not choices else ("0" if "0" in choices else choices[0])
            else:
                value = 1 if not choices else ("1" if "1" in choices else choices[-1])
            result = self.set_setting(name, value)
            # Refresh cached current for next toggle.
            self.capabilities = self.probe_capabilities()
            return result

        raise RuntimeError(f"No default trigger for action '{label}' — set a value explicitly")

    def set_zoom(self, value: Any) -> dict:
        caps = self.capabilities.get("actions", {}).get("zoom")
        if not caps or not caps.get("supported"):
            raise RuntimeError("Zoom is not supported on this camera")
        return self.set_setting(caps["config"]["name"], value)

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    def capture_photo(self, download: bool = True) -> dict:
        """Capture a still. May briefly interrupt HDMI on some bodies."""
        started = time.time()
        with self._cam_lock:
            if self.camera is None:
                raise RuntimeError("Camera not connected")

            # End live view if the camera exposes it — needed for many Nikons
            # before a still can fire (and flash) over USB.
            try:
                vf = self.camera.get_single_config("viewfinder")
                if vf.get_value() in (1, "1", True):
                    vf.set_value(0)
                    self.camera.set_single_config("viewfinder", vf)
            except gp.GPhoto2Error:
                pass

            if self._in_movie_mode():
                self.last_error = "Camera is in movie mode — switch the dial to a photo mode"
                raise RuntimeError(self.last_error)

            # camera.capture() blocks forever if the body never fires (no focus,
            # no card allowed, ...), so trigger and poll events with a deadline.
            try:
                self.camera.trigger_capture()
                target = self._wait_for_new_file(config.CAPTURE_TIMEOUT_SECONDS)
            except gp.GPhoto2Error as exc:
                self.last_error = str(exc)
                raise RuntimeError(f"Capture failed: {exc}") from exc
            except TimeoutError as exc:
                self.last_error = str(exc)
                raise RuntimeError(str(exc)) from exc

            result: dict[str, Any] = {
                "folder": target.folder,
                "name": target.name,
                "elapsed_s": round(time.time() - started, 3),
                "saved_path": None,
            }

            if download:
                camera_file = self.camera.file_get(
                    target.folder,
                    target.name,
                    gp.GP_FILE_TYPE_NORMAL,
                )
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{stamp}_{target.name}"
                path = self.capture_dir / filename
                camera_file.save(str(path))
                result["saved_path"] = str(path)
                result["filename"] = filename

            self.last_capture = result
            self.last_error = None
            log.info("Captured %s in %ss", target.name, result["elapsed_s"])
            return result

    def _in_movie_mode(self) -> bool:
        # Canon EOS ignores still releases while the body is in a movie mode.
        try:
            widget = self.camera.get_single_config("eosmovieswitch")  # type: ignore[union-attr]
            return str(widget.get_value()) == "1"
        except gp.GPhoto2Error:
            return False

    def _wait_for_new_file(self, timeout_s: float) -> gp.CameraFilePath:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            event_type, data = self.camera.wait_for_event(500)  # type: ignore[union-attr]
            if event_type == gp.GP_EVENT_FILE_ADDED:
                return data
        raise TimeoutError(
            f"Camera did not deliver a photo within {timeout_s:.0f}s "
            "(no focus? 'Release shutter w/o card' disabled?)"
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "connected": self.connected and self.camera is not None,
            "model": self.model,
            "connected_at": self.connected_at,
            "error": self.last_error,
            "capabilities": self.capabilities,
            "last_capture": self.last_capture,
        }
