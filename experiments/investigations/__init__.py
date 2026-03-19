"""Registry of all investigation scripts and presets."""

REGISTRY = {
    "scrollbar": {
        "module": "experiments.investigations.scrollbar",
        "description": "Scrollbar width detection (100% reliable for headless)",
        "estimated_minutes": 3,
        "modes": ["headful", "headless"],
        "reliable": True,
    },
    "chrome": {
        "module": "experiments.investigations.chrome",
        "description": "Full Chrome investigation suite (outer/inner gap, lazy loading, fonts, media queries)",
        "estimated_minutes": 10,
        "modes": ["headful", "headless"],
        "reliable": True,
    },
    "chrome_deep": {
        "module": "experiments.investigations.chrome_deep",
        "description": "Deep window chrome detection with additional creative signals",
        "estimated_minutes": 8,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "lazy": {
        "module": "experiments.investigations.lazy",
        "description": "Focused lazy loading behavior differences between headful and headless",
        "estimated_minutes": 5,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "threshold": {
        "module": "experiments.investigations.threshold",
        "description": "Fine-grained lazy loading threshold sweep (connection type spoofing, exact pixel boundary)",
        "estimated_minutes": 8,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "browsers": {
        "module": "experiments.investigations.browsers",
        "description": "Cross-browser comparison (Chromium vs Chrome, headful vs headless)",
        "estimated_minutes": 5,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "rendering": {
        "module": "experiments.investigations.rendering",
        "description": "Rendering stress timing analysis (heavy elements, CSS complexity, SVG filters)",
        "estimated_minutes": 10,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "render_ratio": {
        "module": "experiments.investigations.render_ratio",
        "description": "Render cost ratio comparison (heavy/light CSS timing, statistical significance)",
        "estimated_minutes": 8,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "stress_optimal": {
        "module": "experiments.investigations.stress_optimal",
        "description": "Optimal stress test parameter tuning (element count, CSS complexity, beacon density)",
        "estimated_minutes": 10,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "compositor": {
        "module": "experiments.investigations.compositor",
        "description": "GPU compositor behavior analysis (animation-based detection, vsync timing)",
        "estimated_minutes": 8,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "combined_classifier": {
        "module": "experiments.investigations.combined_classifier",
        "description": "Multi-signal threshold classifier combining all discovered detection signals",
        "estimated_minutes": 15,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "image_loading": {
        "module": "experiments.investigations.image_loading",
        "description": "IntersectionObserver-based image loading pattern analysis (fanbox.cc pattern)",
        "estimated_minutes": 5,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "ad_cascade": {
        "module": "experiments.investigations.ad_cascade",
        "description": "Ad-tech timing cascade analysis (prebid.js cookie-sync, visibility API differences)",
        "estimated_minutes": 10,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
    "check_ect": {
        "module": "experiments.investigations.check_ect",
        "description": "Network effective connection type (ECT) validation across headful and headless",
        "estimated_minutes": 2,
        "modes": ["headful", "headless"],
        "reliable": False,
    },
}

# Presets
QUICK = ["scrollbar", "chrome"]  # ~5 min, most reliable signals
SHELL = ["browsers", "lazy", "threshold", "check_ect"]  # headless-shell specific
ALL = list(REGISTRY.keys())
