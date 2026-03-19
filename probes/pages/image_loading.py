from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/image-loading")
async def image_loading_page(
    s: str = Query(..., description="Session ID"),
    positions: str = Query(
        "0,100,300,500,720,1000,1500,2000,3000,5000,8000",
        description="Comma-separated pixel positions for test images",
    ),
):
    """IntersectionObserver-based image loading detection.

    Reproduces fanbox.cc-style JS lazy loading where initial HTML
    contains no image URLs.  JavaScript uses IntersectionObserver to
    set src attributes when elements enter the viewport.

    Tests multiple JS-based loading mechanisms to identify which
    create detectable differences between headful and headless Chrome.

    Sections:
      1. Control (eager <img>)          — io-ctrl-{pos}
      2. IO + src injection             — io-src-{pos}
      3. IO + rootMargin=0px            — io-margin0-{pos}
      4. IO + rootMargin=200px          — io-margin200-{pos}
      5. IO + rootMargin=1000px         — io-margin1000-{pos}
      6. IO + new Image()               — io-newimg-{pos}
      7. IO + img.decode()              — io-decode-{pos}
      8. IO + CSS background-image      — io-bgimg-{pos}
      9. IO + fetch()                   — io-fetch-{pos}
     10. IO + React simulation          — io-react-{pos}
    """
    pos_list = [int(p.strip()) for p in positions.split(",")]
    max_pos = max(pos_list)
    page_height = max_pos + 200

    # --- Build HTML elements ---

    # Section 1: Control — eager <img> tags (no JS involved)
    ctrl_elements = []
    for pos in pos_list:
        ctrl_elements.append(
            f'<img src="/track/io-ctrl-{pos}?s={s}" '
            f'width="10" height="10" loading="eager" '
            f'style="position:absolute;top:{pos}px;left:0;">'
        )

    # Sections 2-10: JS-managed probe elements (no src initially)
    # Each section uses <div> or <img> placeholders at different left offsets
    probe_elements = []
    sections = [
        ("io-src", 20),
        ("io-margin0", 40),
        ("io-margin200", 60),
        ("io-margin1000", 80),
        ("io-newimg", 100),
        ("io-decode", 120),
        ("io-bgimg", 140),
        ("io-fetch", 160),
        ("io-react", 180),
    ]

    for group, left in sections:
        for pos in pos_list:
            if group == "io-src":
                # <img> with data-src, observer will set src
                probe_elements.append(
                    f'<img data-group="{group}" data-src="/track/{group}-{pos}?s={s}" '
                    f'width="10" height="10" '
                    f'style="position:absolute;top:{pos}px;left:{left}px;">'
                )
            elif group == "io-react":
                # Container div — JS will inject placeholder inside
                probe_elements.append(
                    f'<div data-group="{group}" data-src="/track/{group}-{pos}?s={s}" '
                    f'style="position:absolute;top:{pos}px;left:{left}px;width:10px;height:10px;">'
                    f'</div>'
                )
            else:
                # Generic sentinel div
                probe_elements.append(
                    f'<div data-group="{group}" data-src="/track/{group}-{pos}?s={s}" '
                    f'style="position:absolute;top:{pos}px;left:{left}px;width:10px;height:10px;">'
                    f'</div>'
                )

    js = _build_js(s)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>JS-based Image Loading Probes</title>
    <style>
        body {{ margin: 0; padding: 0; height: {page_height}px; position: relative; }}
    </style>
</head>
<body>
{chr(10).join(ctrl_elements)}
{chr(10).join(probe_elements)}
<script>
{js}
</script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def _build_js(session_id: str) -> str:
    """Generate the inline JavaScript for all IO-based test sections."""
    return f"""
(function() {{
    "use strict";

    // ---- Section 2: IO + src injection (fanbox.cc core pattern) ----
    var ioSrcObserver = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                entry.target.src = entry.target.dataset.src;
                ioSrcObserver.unobserve(entry.target);
            }}
        }});
    }});
    document.querySelectorAll('[data-group="io-src"]').forEach(function(el) {{
        ioSrcObserver.observe(el);
    }});

    // ---- Section 3: IO + rootMargin=0px ----
    var ioMargin0Observer = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var img = new Image();
                img.src = entry.target.dataset.src;
                entry.target.appendChild(img);
                ioMargin0Observer.unobserve(entry.target);
            }}
        }});
    }}, {{ rootMargin: "0px" }});
    document.querySelectorAll('[data-group="io-margin0"]').forEach(function(el) {{
        ioMargin0Observer.observe(el);
    }});

    // ---- Section 4: IO + rootMargin=200px ----
    var ioMargin200Observer = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var img = new Image();
                img.src = entry.target.dataset.src;
                entry.target.appendChild(img);
                ioMargin200Observer.unobserve(entry.target);
            }}
        }});
    }}, {{ rootMargin: "200px" }});
    document.querySelectorAll('[data-group="io-margin200"]').forEach(function(el) {{
        ioMargin200Observer.observe(el);
    }});

    // ---- Section 5: IO + rootMargin=1000px ----
    var ioMargin1000Observer = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var img = new Image();
                img.src = entry.target.dataset.src;
                entry.target.appendChild(img);
                ioMargin1000Observer.unobserve(entry.target);
            }}
        }});
    }}, {{ rootMargin: "1000px" }});
    document.querySelectorAll('[data-group="io-margin1000"]').forEach(function(el) {{
        ioMargin1000Observer.observe(el);
    }});

    // ---- Section 6: IO + new Image() (programmatic, not in DOM) ----
    var ioNewImgObserver = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var img = new Image();
                img.src = entry.target.dataset.src;
                // Intentionally NOT appended to DOM
                ioNewImgObserver.unobserve(entry.target);
            }}
        }});
    }});
    document.querySelectorAll('[data-group="io-newimg"]').forEach(function(el) {{
        ioNewImgObserver.observe(el);
    }});

    // ---- Section 7: IO + img.decode() ----
    var ioDecodeObserver = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var img = document.createElement("img");
                img.src = entry.target.dataset.src;
                img.width = 10;
                img.height = 10;
                var target = entry.target;
                img.decode().then(function() {{
                    target.appendChild(img);
                }}).catch(function() {{
                    // Decode failed but request was still made
                    target.appendChild(img);
                }});
                ioDecodeObserver.unobserve(entry.target);
            }}
        }});
    }});
    document.querySelectorAll('[data-group="io-decode"]').forEach(function(el) {{
        ioDecodeObserver.observe(el);
    }});

    // ---- Section 8: IO + CSS background-image via JS ----
    var ioBgImgObserver = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                entry.target.style.backgroundImage = 'url("' + entry.target.dataset.src + '")';
                ioBgImgObserver.unobserve(entry.target);
            }}
        }});
    }});
    document.querySelectorAll('[data-group="io-bgimg"]').forEach(function(el) {{
        ioBgImgObserver.observe(el);
    }});

    // ---- Section 9: IO + fetch() ----
    var ioFetchObserver = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                fetch(entry.target.dataset.src).catch(function() {{}});
                ioFetchObserver.unobserve(entry.target);
            }}
        }});
    }});
    document.querySelectorAll('[data-group="io-fetch"]').forEach(function(el) {{
        ioFetchObserver.observe(el);
    }});

    // ---- Section 10: IO + React simulation ----
    // Phase 1: Inject placeholder divs (simulating React mount)
    var ioReactObserver = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var img = document.createElement("img");
                img.src = entry.target.dataset.src;
                img.width = 10;
                img.height = 10;
                entry.target.parentNode.replaceChild(img, entry.target);
                ioReactObserver.unobserve(entry.target);
            }}
        }});
    }});
    document.querySelectorAll('[data-group="io-react"]').forEach(function(container) {{
        var placeholder = document.createElement("div");
        placeholder.dataset.src = container.dataset.src;
        placeholder.style.width = "10px";
        placeholder.style.height = "10px";
        container.appendChild(placeholder);
        ioReactObserver.observe(placeholder);
    }});

}})();
"""
