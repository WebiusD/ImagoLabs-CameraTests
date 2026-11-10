#!/usr/bin/env python3
"""HDMI + gphoto2 simultaneous-operation test bench.

Opens a web UI that:
  1. Streams the camera's HDMI output via a USB capture card
  2. Controls the camera over USB with gphoto2
  3. Surfaces clear status so you can see whether HDMI survives USB control

Patterns adapted from ImagoLabs-DreamMachine (OpenCV preview loop + persistent
gphoto2 session + multipart MJPEG stream).
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

import config
from gphoto_control import GphotoControl
from hdmi_capture import HdmiCapture

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("cameratest")

app = Flask(__name__)
hdmi = HdmiCapture(device=config.HDMI_DEVICE)
camera = GphotoControl(capture_dir=config.CAPTURE_DIR)

# Lightweight event log shown in the UI to help interpret the test.
_events: list[dict] = []
_MAX_EVENTS = 80


def note(message: str, level: str = "info") -> None:
    entry = {"t": time.time(), "level": level, "message": message}
    _events.append(entry)
    if len(_events) > _MAX_EVENTS:
        del _events[: len(_events) - _MAX_EVENTS]
    getattr(log, level if level in ("info", "warning", "error") else "info")(message)


# ---------------------------------------------------------------------------
# Pages / stream
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/stream")
def stream():
    def generate():
        while True:
            frame = hdmi.get_jpeg()
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.03)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/captures/<path:filename>")
def serve_capture(filename: str):
    return send_from_directory(config.CAPTURE_DIR, filename)


# ---------------------------------------------------------------------------
# Status / discovery
# ---------------------------------------------------------------------------
@app.get("/api/status")
def api_status():
    hdmi_status = hdmi.status()
    cam_status = camera.status()
    simultaneous = hdmi_status["alive"] and cam_status["connected"]
    return jsonify(
        {
            "hdmi": hdmi_status,
            "camera": cam_status,
            "simultaneous_ok": simultaneous,
            "events": _events[-40:],
        }
    )


@app.get("/api/devices")
def api_devices():
    return jsonify({"video_devices": hdmi.list_devices()})


# ---------------------------------------------------------------------------
# HDMI controls
# ---------------------------------------------------------------------------
@app.post("/api/hdmi/start")
def api_hdmi_start():
    data = request.get_json(silent=True) or {}
    device = data.get("device", hdmi.device)
    try:
        device = int(device)
        status = hdmi.start(device)
        note(f"HDMI stream started on device {device}")
        return jsonify({"ok": True, "hdmi": status})
    except Exception as exc:
        note(f"HDMI start failed: {exc}", "error")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/hdmi/stop")
def api_hdmi_stop():
    status = hdmi.stop()
    note("HDMI stream stopped")
    return jsonify({"ok": True, "hdmi": status})


@app.post("/api/hdmi/restart")
def api_hdmi_restart():
    try:
        before = hdmi.status()
        status = hdmi.restart()
        note(
            f"HDMI stream restarted (was state={before['state']}, "
            f"frames={before['frames_received']})"
        )
        return jsonify({"ok": True, "hdmi": status})
    except Exception as exc:
        note(f"HDMI restart failed: {exc}", "error")
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# gphoto2 controls
# ---------------------------------------------------------------------------
@app.post("/api/camera/connect")
def api_camera_connect():
    hdmi_before = hdmi.status()
    try:
        status = camera.connect()
        hdmi_after = hdmi.status()
        note(
            f"gphoto2 connected ({status.get('model')}). "
            f"HDMI before={hdmi_before['state']}/{hdmi_before['frames_received']} frames, "
            f"after={hdmi_after['state']}/{hdmi_after['frames_received']} frames"
        )
        if hdmi_before["alive"] and not hdmi_after["alive"]:
            note(
                "HDMI signal was lost when USB/gphoto2 connected — "
                "this camera likely cannot stream HDMI and be controlled over USB at once.",
                "warning",
            )
        elif hdmi_after["alive"] and status["connected"]:
            note("HDMI still alive after USB connect — simultaneous operation looks possible.")
        return jsonify({"ok": True, "camera": status, "hdmi": hdmi_after})
    except Exception as exc:
        note(f"gphoto2 connect failed: {exc}", "error")
        return jsonify({"ok": False, "error": str(exc), "hdmi": hdmi.status()}), 500


@app.post("/api/camera/disconnect")
def api_camera_disconnect():
    status = camera.disconnect()
    note("gphoto2 disconnected")
    return jsonify({"ok": True, "camera": status, "hdmi": hdmi.status()})


@app.post("/api/camera/refresh-capabilities")
def api_refresh_capabilities():
    try:
        caps = camera.probe_capabilities()
        camera.capabilities = caps
        note("Capabilities re-probed")
        return jsonify({"ok": True, "capabilities": caps})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/camera/setting/<name>")
def api_get_setting(name: str):
    try:
        return jsonify({"ok": True, "setting": camera.get_setting(name)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/camera/setting/<name>")
def api_set_setting(name: str):
    data = request.get_json(silent=True) or {}
    if "value" not in data:
        return jsonify({"ok": False, "error": "Missing 'value'"}), 400
    hdmi_before = hdmi.status()
    try:
        setting = camera.set_setting(name, data["value"])
        hdmi_after = hdmi.status()
        note(
            f"Set {name}={data['value']}. HDMI alive: "
            f"{hdmi_before['alive']} → {hdmi_after['alive']}"
        )
        return jsonify({"ok": True, "setting": setting, "hdmi": hdmi_after})
    except Exception as exc:
        note(f"Set {name} failed: {exc}", "error")
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/camera/action/<label>")
def api_action(label: str):
    data = request.get_json(silent=True) or {}
    try:
        if label == "zoom" and "value" in data:
            result = camera.set_zoom(data["value"])
        else:
            result = camera.trigger_action(label)
        note(f"Action '{label}' OK")
        return jsonify({"ok": True, "result": result, "hdmi": hdmi.status()})
    except Exception as exc:
        note(f"Action '{label}' failed: {exc}", "warning")
        return jsonify({"ok": False, "error": str(exc), "hdmi": hdmi.status()}), 400


@app.post("/api/camera/capture")
def api_capture():
    hdmi_before = hdmi.status()
    auto_restart = bool((request.get_json(silent=True) or {}).get("restart_hdmi", True))
    try:
        result = camera.capture_photo()
        # Give the body a moment; many cameras blank HDMI during shutter.
        time.sleep(0.5)
        hdmi_mid = hdmi.status()
        restarted = False
        if auto_restart and not hdmi_mid["alive"]:
            try:
                hdmi.restart()
                time.sleep(0.8)
                restarted = True
            except Exception as restart_exc:
                note(f"Auto HDMI restart after capture failed: {restart_exc}", "error")
        hdmi_after = hdmi.status()
        note(
            f"Photo captured ({result.get('filename')}). "
            f"HDMI: {hdmi_before['state']} → during/after {hdmi_mid['state']} → "
            f"final {hdmi_after['state']}"
            + (" (auto-restarted)" if restarted else "")
        )
        return jsonify(
            {
                "ok": True,
                "capture": result,
                "hdmi_before": hdmi_before,
                "hdmi_after_capture": hdmi_mid,
                "hdmi": hdmi_after,
                "hdmi_restarted": restarted,
            }
        )
    except Exception as exc:
        note(f"Capture failed: {exc}", "error")
        return jsonify({"ok": False, "error": str(exc), "hdmi": hdmi.status()}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="HDMI + gphoto2 camera test bench")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--device",
        type=int,
        default=config.HDMI_DEVICE,
        help="OpenCV / V4L2 index of the HDMI capture card",
    )
    parser.add_argument(
        "--auto-hdmi",
        action="store_true",
        help="Start HDMI streaming immediately on launch",
    )
    args = parser.parse_args()

    config.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    hdmi.device = args.device

    if args.auto_hdmi:
        try:
            hdmi.start(args.device)
            note(f"Auto-started HDMI on device {args.device}")
        except Exception as exc:
            note(f"Auto HDMI start failed: {exc}", "warning")

    note("CameraTest ready — open the web UI to begin the compatibility checklist")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
