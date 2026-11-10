"""Simple runtime defaults for the HDMI + gphoto2 compatibility test."""

from pathlib import Path

# OpenCV / V4L2 index of the HDMI capture card. Use the UI or --device to override.
HDMI_DEVICE = 2

# Preferred capture resolution (capture cards often ignore this).
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# Requested capture-card frame rate. Without it the card falls back to 10 fps.
HDMI_FPS = 30

# Aspect ratio the previews are cropped to (None = no crop).
PREVIEW_ASPECT = 16 / 9

# Aspect of the picture inside the HDMI frame. None = auto-detect black side
# bars (photo mode sends a 3:2 picture inside 16:9); e.g. 3 / 2 to force it.
HDMI_CONTENT_ASPECT = None

# MJPEG stream quality (1–100).
JPEG_QUALITY = 75

# How long without a new HDMI frame before status shows "stale / lost".
FRAME_STALE_SECONDS = 1.5

# USB live view (gphoto2 capture_preview) frames older than this count as lost.
USB_PREVIEW_STALE_SECONDS = 2.0

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
