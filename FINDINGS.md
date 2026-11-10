# Canon EOS R50 V: HDMI + gphoto2 findings

Setup: R50 V → HDMI → Guermok "USB2 Video" capture card, plus R50 V → USB (gphoto2 / libgphoto2 2.5.34). Tested Nov 2026.

## Works

- HDMI preview and USB control (gphoto2) run at the same time.
- Photos over USB straight to the PC: `capturetarget = Internal RAM`, nothing is stored on the card (~1 s, full-res JPEG). Note: an SD card was in the camera during the successful tests. Without a card, Canon also needs "Release shutter w/o card" enabled (not verified).
- HDMI preview at 30 fps and USB live view at ~30 fps simultaneously, photos taken during both.

## Surprises and gotchas

### Camera

- **The A+/video mode is a movie mode.** gphoto2 reports `autoexposuremode = Auto` in both photo and movie modes; only `eosmovieswitch` (1 = movie) tells them apart. In movie mode the camera accepts the shutter command (button events arrive) but never takes a photo, and `camera.capture()` hangs forever. **Photos only work with the dial in a photo mode.**
- **HDMI works in photo mode too**, contrary to the first impression: clean output (no overlays), but a 3:2 picture inside a 1920×1080 frame with black side bars.
- **The shooting mode can't be changed over USB.** Writes to `autoexposuremode`, `autoexposuremodedial` and `eosmoviemode` are silently ignored.
- **`eosremoterelease` fails in libgphoto2 2.5.34 (Python)** with "Unsupported operation", but works with the 2.5.28 CLI. Not needed: `trigger_capture()` + waiting for `FILE_ADDED` works.
- In standby the camera still answers over USB, but HDMI shows "No Video" and live view fails with `I/O in progress`.

### USB live view vs. HDMI

- **USB live view switches HDMI off.** gphoto2 sets the EVF output (`output`) to `PC`, and HDMI mirrors only the rear screen (`TFT`). Stopping the live view doesn't bring HDMI back.
- **Fix: set `output = "TFT + PC"` before the first `capture_preview()`.** Then both run in parallel with no HDMI dropout. Setting `output = "TFT"` afterwards ends USB live view without interruption.
- **The Nikon-style `viewfinder = 0` before a photo is harmful on Canon:** it sets `output = Off` and kills HDMI. Canon also shoots fine during live view.
- Opening a new gphoto2 session also resets the output to `TFT`, but HDMI then only returns after ~5 s.
- **USB live view resolution is fixed at 960×640** (3:2, 960×540 after the 16:9 crop). There's no size setting (no `liveviewsize`; only the EVF properties `d1b0`–`d1bc`). In photo mode it reaches ~30 fps, in movie mode only ~16 fps (1024×576).

### Capture card / HDMI

- **The card defaults to 10 fps.** OpenCV must set FOURCC `MJPG` *before* size/fps and explicitly request `CAP_PROP_FPS = 30` (YUYV only manages 10 fps at 1080p).
- **OpenCV's internal MJPEG decoding is the bottleneck (~15 fps at 1080p).** Taking the raw MJPEG data (`CAP_PROP_CONVERT_RGB = 0`) and decoding with `cv2.imdecode` (~7 ms/frame) gives a steady 30 fps.
- **The card reports "streaming" without a signal:** it sends its own "No Video" screen at full frame rate. Frame counters alone don't prove a picture is there.
- **The `/dev/videoN` number changes** (2 ↔ 3) when the camera is power-cycled or replugged. Index 0 is the laptop webcam, so an accidental fallback to 0 shows the wrong image.
- **Higher HDMI resolution brings nothing.** The camera sends 1080p (the recording-resolution menu doesn't change that); the card's 2560×1440 mode is just a scaled-up 1080p image (practically no information beyond 1080p). Effective preview: 1620×911 after the 16:9 crop.

## Recommended setup

Camera dial in **photo mode**, auto power-off disabled, "Release shutter w/o card" enabled. Use HDMI (1080p, 30 fps) as the preview and USB only for photos and settings. Use USB live view only as a fallback or for comparison, always with `output = "TFT + PC"`.
