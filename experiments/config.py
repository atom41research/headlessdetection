from core.config import (
    BASE_URL,
    HTTPS_BASE_URL,
    MODE_PARAMS,
    DEFAULT_VIEWPORT as MATCHED_VIEWPORT,
    SETTLE_TIME,
    CHROME_USER_AGENT,
)

# Re-export for backwards compat
DEFAULT_RUNS = 30

PAGES = [
    "media-queries",
    "lazy-loading",
    "import-chains",
    "background-chains",
    "font-loading",
    "combined",
    "image-loading",
    "scrollbar-width",
]

SERVER_SIGNAL_PAGES = [
    "probe-tls-fingerprint",
    "probe-header-order",
    "probe-connection-reuse",
    "probe-prefetch-tls",
]
