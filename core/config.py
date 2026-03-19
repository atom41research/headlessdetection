"""Central configuration for browser launching and detection experiments.

All browser mode parameters, stealth flags, and viewport settings are
defined here.  Every other module imports from this file instead of
duplicating constants.
"""

# System Chrome channel name (Playwright)
CHANNEL = "chrome"

# Playwright channel for the stripped headless-shell binary
HEADLESS_SHELL_CHANNEL = "chromium-headless-shell"

# Stealth flags applied to every browser launch
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
]

# Default viewport for all experiments
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

# Mode name → (channel, headless flag)
MODE_PARAMS: dict[str, tuple[str, bool]] = {
    "headful": ("chrome", False),
    "headless": ("chrome", True),
    "headless-shell": ("chromium-headless-shell", True),
}

# Seconds to wait after networkidle before collecting results
SETTLE_TIME = 2.0

# Server URLs (probe server)
BASE_URL = "http://127.0.0.1:8000"
HTTPS_BASE_URL = "https://127.0.0.1:8443"

# Detector server URL
DETECTOR_URL = "http://127.0.0.1:8099"

# Populated at runtime by detect_chrome_ua()
CHROME_USER_AGENT: str | None = None
