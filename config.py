"""Simple runtime defaults for the HDMI + gphoto2 compatibility test."""

from pathlib import Path

# OpenCV / V4L2 index of the HDMI capture card. Use the UI or --device to override.
HDMI_DEVICE = 2

# Preferred capture resolution (capture cards often ignore this).
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# MJPEG stream quality (1–100).
JPEG_QUALITY = 75

# How long without a new HDMI frame before status shows "stale / lost".
FRAME_STALE_SECONDS = 1.5

# Max time to wait for the camera to deliver a photo after triggering.
CAPTURE_TIMEOUT_SECONDS = 15

# Directory for photos downloaded via gphoto2.
CAPTURE_DIR = Path(__file__).resolve().parent / "captures"

# Common gphoto2 config names to probe. Cameras expose different subsets.
EXPOSURE_SETTINGS = (
    "iso",
    "shutterspeed",
    "aperture",
    "exposurecompensation",
    "whitebalance",
    "imagequality",
    "capturetarget",
)

ACTION_SETTINGS = (
    ("autofocus", ("autofocusdrive", "autofocus", "focusmode")),
    ("zoom", ("zoom", "zoomratio", "manualfocusdrive")),
    ("viewfinder", ("viewfinder",)),
)
