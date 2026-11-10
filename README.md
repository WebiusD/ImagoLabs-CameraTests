# CameraTest — HDMI + gphoto2 compatibility bench

Minimal Python web app to answer one question:

> Can this camera keep a live HDMI feed (via USB capture card) **while** being controlled over USB with `gphoto2`?

Built for hardware triage (e.g. Nikon D7200 blanks HDMI when USB is plugged in). Approaches for streaming and camera control are adapted from [ImagoLabs-DreamMachine](https://github.com/WebiusD/ImagoLabs-DreamMachine) (OpenCV preview loop, persistent libgphoto2 session, MJPEG multipart stream).

## What it tests

| Check | How |
| --- | --- |
| HDMI alone works | Start stream with camera USB unplugged |
| USB kills HDMI | Connect USB / **Connect USB** in the UI and watch the status badge + frame age |
| Settings while streaming | Change ISO / shutter / aperture and see if HDMI stays alive |
| Zoom / AF | Shown only if gphoto2 exposes matching configs; otherwise marked unsupported |
| Capture vs HDMI | Capture a photo; note interruption; optional auto-restart of the capture device |

## Hardware

1. Camera HDMI out → USB HDMI capture card → PC  
2. Camera USB → PC (for gphoto2)  
3. Prefer a clean HDMI feed (info overlay off) if the body supports it  

## Setup (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y gphoto2 libgphoto2-dev python3-venv python3-dev \
  v4l-utils pkg-config

cd ~/Desktop/CameraTest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Confirm the capture card and camera are visible:

```bash
v4l2-ctl --list-devices
gphoto2 --auto-detect
```

If `gphoto2` fails with “Could not claim the USB device”, unmount the camera from the file manager or:

```bash
pkill -f gvfs-gphoto2-volume-monitor; pkill -f gvfsd-gphoto2
```

(The app also tries this on connect.)

## Run

```bash
source .venv/bin/activate
python app.py                  # http://0.0.0.0:8080
python app.py --device 0 --auto-hdmi
```

Open `http://localhost:8080`.

## Suggested procedure

1. HDMI cable only — **Scan** devices, pick the capture card, **Start**. Confirm live image and `streaming` state.  
2. Plug USB — click **Connect USB**.  
   - Badge **Simultaneous OK** → HDMI + control can coexist.  
   - Badge **USB connected — HDMI lost** → same class of limitation as the D7200.  
3. Adjust exposure controls; watch frame age.  
4. **Capture photo** (with auto-restart enabled). Check whether HDMI recovers.  
5. Use the event log as a short test report.

Photos land in `captures/`.

## Project layout

```
app.py              Flask UI + API
hdmi_capture.py     OpenCV / V4L2 capture-card reader
gphoto_control.py   Persistent gphoto2 session + capability probe
config.py           Defaults (device index, stale threshold, …)
templates/          Web UI
static/             CSS / JS
captures/           Downloaded stills
```

## Notes

- Some bodies disable Live View / HDMI whenever USB PTP is active — that is a camera limitation, not a bug in this tool.  
- A short HDMI blank during shutter is acceptable if **Restart** (or auto-restart) brings the stream back.  
- Unsupported zoom/AF configs are detected at connect time and disabled in the UI.  
- On Linux the capture backend uses V4L2 (`cv2.CAP_V4L2`), matching DreamMachine’s OpenCV path (which used DirectShow on Windows).  
