"""Browser-based data collection for a single URL visit."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import (
    Playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PwTimeout,
)

from . import config

METRICS_JS = """
() => {
    const bodyText = document.body ? document.body.innerText || '' : '';

    // Count every element tag name
    const tagCounts = {};
    for (const el of document.querySelectorAll('*')) {
        const tag = el.tagName.toLowerCase();
        tagCounts[tag] = (tagCounts[tag] || 0) + 1;
    }

    // Structural elements
    const structural = ['nav', 'main', 'footer', 'article', 'header', 'aside',
                        'section', 'form', 'table', 'dialog'];
    const structuralPresent = {};
    for (const tag of structural) {
        structuralPresent[tag] = (tagCounts[tag] || 0) > 0;
    }

    return {
        page_title: document.title || '',
        visible_text_length: bodyText.length,
        tag_counts: tagCounts,
        dom_element_count: document.querySelectorAll('*').length,
        structural_present: structuralPresent,
    };
}
"""

WEBDRIVER_PATCH = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)


@dataclass
class PageMetrics:
    url: str
    final_url: str = ""
    mode: str = ""
    page_title: str = ""
    dom_element_count: int = 0
    visible_text_length: int = 0
    tag_counts: dict[str, int] = field(default_factory=dict)
    structural_present: dict[str, bool] = field(default_factory=dict)
    request_counts_by_type: dict[str, int] = field(default_factory=dict)
    network_request_count: int = 0
    console_errors: list[str] = field(default_factory=list)
    screenshot_path: str = ""
    har_path: str = ""
    error: str = ""
    http_status: int = 0


async def collect_page_data(
    pw: Playwright,
    url: str,
    mode: str,
    output_dir: Path,
    host_slug: str,
) -> PageMetrics:
    """Visit url in the given mode and collect metrics, screenshot, and HAR."""
    channel, headless = config.MODE_PARAMS[mode]
    metrics = PageMetrics(url=url, mode=mode)

    har_filename = f"{host_slug}_{mode}.har"
    har_path = output_dir / "har" / har_filename
    screenshot_filename = f"{host_slug}_{mode}.png"
    screenshot_path = output_dir / "screenshots" / screenshot_filename

    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    try:
        browser = await pw.chromium.launch(
            headless=headless,
            channel=channel,
            args=config.BROWSER_ARGS,
        )
        ctx_opts: dict = {
            "viewport": config.VIEWPORT,
            "record_har_path": str(har_path),
        }
        ctx_opts["user_agent"] = config.USER_AGENT
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()

        # Hide navigator.webdriver signal
        await page.add_init_script(WEBDRIVER_PATCH)

        console_errors: list[str] = []
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text)
            if msg.type == "error"
            else None,
        )

        request_count = 0
        request_type_counts: dict[str, int] = {}

        def _on_request(req):
            nonlocal request_count
            request_count += 1
            rtype = req.resource_type
            request_type_counts[rtype] = request_type_counts.get(rtype, 0) + 1

        page.on("request", _on_request)

        # Navigate — timeout is non-fatal, we collect whatever loaded
        response = None
        try:
            response = await page.goto(
                url,
                wait_until=config.WAIT_UNTIL,
                timeout=config.PAGE_TIMEOUT_MS,
            )
        except PwTimeout:
            pass  # page partially loaded — continue to metrics

        # Brief settle for dynamic content
        await asyncio.sleep(config.SETTLE_TIME_S)

        metrics.http_status = response.status if response else 0
        metrics.final_url = page.url
        metrics.network_request_count = request_count
        metrics.request_counts_by_type = request_type_counts
        metrics.console_errors = console_errors[:20]

        # Collect DOM metrics
        try:
            js_data = await page.evaluate(METRICS_JS)
            metrics.page_title = js_data["page_title"]
            metrics.dom_element_count = js_data["dom_element_count"]
            metrics.visible_text_length = js_data["visible_text_length"]
            metrics.tag_counts = js_data["tag_counts"]
            metrics.structural_present = js_data["structural_present"]
        except Exception:
            metrics.error = "JS evaluation failed"

    except Exception as e:
        metrics.error = str(e)[:200]
    finally:
        # Always capture screenshot if page exists
        if page is not None:
            try:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                metrics.screenshot_path = screenshot_filename
            except Exception:
                pass

        # Close context to flush HAR file
        if context is not None:
            try:
                await context.close()
                metrics.har_path = har_filename
            except Exception:
                pass

        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass

    return metrics
