"""Playwright browser launch, URL fetching, and monitor coordination."""

import asyncio
import time
from dataclasses import dataclass, field

from playwright.async_api import (
    Playwright,
    TimeoutError as PwTimeout,
)

from . import config
from .monitor import MonitorResult, find_chrome_pid, monitor_process_tree

WEBDRIVER_PATCH = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)

# JS to capture Performance timing milestones (Navigation Timing Level 2)
CONTENT_CHECK_JS = "document.body ? document.body.innerText.length : -1"

PAGE_METRICS_JS = """
() => {
    const m = {};

    // DOM metrics
    m.dom_element_count = document.querySelectorAll('*').length;
    m.visible_text_length = document.body ? (document.body.innerText || '').length : 0;

    // Element type counts
    m.script_count = document.querySelectorAll('script').length;
    m.stylesheet_count = document.querySelectorAll('link[rel="stylesheet"], style').length;
    m.image_count = document.querySelectorAll('img').length;
    m.iframe_count = document.querySelectorAll('iframe').length;
    m.anchor_count = document.querySelectorAll('a[href]').length;
    m.form_count = document.querySelectorAll('form').length;

    // Resource Timing API
    const resources = performance.getEntriesByType('resource');
    m.resource_count = resources.length;
    let transferBytes = 0;
    let decodedBytes = 0;
    const byType = {};
    for (const r of resources) {
        transferBytes += r.transferSize || 0;
        decodedBytes += r.decodedBodySize || 0;
        const t = r.initiatorType || 'other';
        byType[t] = (byType[t] || 0) + 1;
    }
    m.total_transfer_bytes = transferBytes;
    m.total_decoded_bytes = decodedBytes;
    m.resources_by_type = byType;

    // Page dimensions
    m.document_height = Math.max(
        document.body ? document.body.scrollHeight : 0,
        document.documentElement ? document.documentElement.scrollHeight : 0
    );
    m.document_width = Math.max(
        document.body ? document.body.scrollWidth : 0,
        document.documentElement ? document.documentElement.scrollWidth : 0
    );

    return m;
}
"""

LOAD_EVENTS_JS = """
() => {
    const nav = performance.getEntriesByType('navigation')[0];
    if (!nav) return null;
    return {
        dns_ms: nav.domainLookupEnd - nav.domainLookupStart,
        connect_ms: nav.connectEnd - nav.connectStart,
        ttfb_ms: nav.responseStart,
        response_ms: nav.responseEnd - nav.responseStart,
        dom_interactive_ms: nav.domInteractive > 0 ? nav.domInteractive : -1,
        dom_content_loaded_ms: nav.domContentLoadedEventEnd > 0 ? nav.domContentLoadedEventEnd : -1,
        dom_complete_ms: nav.domComplete > 0 ? nav.domComplete : -1,
        load_event_ms: nav.loadEventEnd > 0 ? nav.loadEventEnd : -1,
    };
}
"""


@dataclass
class LoadEvents:
    dns_ms: float = -1
    connect_ms: float = -1
    ttfb_ms: float = -1
    response_ms: float = -1
    dom_interactive_ms: float = -1
    dom_content_loaded_ms: float = -1
    dom_complete_ms: float = -1
    load_event_ms: float = -1


@dataclass
class PageMetrics:
    """Page-level structural and resource metrics collected via JS evaluation."""
    # DOM structure
    dom_element_count: int = 0
    visible_text_length: int = 0
    script_count: int = 0
    stylesheet_count: int = 0
    image_count: int = 0
    iframe_count: int = 0
    anchor_count: int = 0
    form_count: int = 0
    # Resource Timing API
    resource_count: int = 0
    total_transfer_bytes: int = 0
    total_decoded_bytes: int = 0
    resources_by_type: dict[str, int] = field(default_factory=dict)
    # Page dimensions
    document_height: int = 0
    document_width: int = 0


@dataclass
class BenchmarkRun:
    url: str
    mode: str
    run_index: int
    monitor_result: MonitorResult = field(default_factory=MonitorResult)
    page_load_time_ms: float = 0.0
    load_events: LoadEvents = field(default_factory=LoadEvents)
    page_metrics: PageMetrics = field(default_factory=PageMetrics)
    error: str = ""
    # Page load verification
    http_status: int = 0
    final_url: str = ""
    timed_out: bool = False
    content_length: int = -1


_LAUNCH_TIMEOUT_MS = 30_000
_CLOSE_TIMEOUT_S = 10


async def run_benchmark(
    pw: Playwright,
    url: str,
    mode: str,
    run_index: int,
    sample_interval_s: float,
    settle_time_s: float,
    page_timeout_ms: int,
    user_agent: str = "",
) -> BenchmarkRun:
    """Run a single benchmark: launch Chrome, navigate, monitor resources, close."""
    channel, headless = config.launch_params(mode)
    result = BenchmarkRun(url=url, mode=mode, run_index=run_index)

    browser = None
    context = None
    page = None
    stop_event = asyncio.Event()
    monitor_task = None

    try:
        browser = await pw.chromium.launch(
            headless=headless,
            channel=channel,
            args=config.BROWSER_ARGS,
            timeout=_LAUNCH_TIMEOUT_MS,
        )

        ctx_opts: dict = {"viewport": config.VIEWPORT}
        if user_agent:
            ctx_opts["user_agent"] = user_agent
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()
        await page.add_init_script(WEBDRIVER_PATCH)

        # Start resource monitor
        chrome_pid = find_chrome_pid(browser)
        if chrome_pid is not None:
            monitor_task = asyncio.create_task(
                monitor_process_tree(chrome_pid, sample_interval_s, stop_event)
            )

        # Navigate
        t0 = time.monotonic()
        response = None
        try:
            response = await page.goto(url, wait_until=config.WAIT_UNTIL, timeout=page_timeout_ms)
        except PwTimeout:
            result.timed_out = True
        except Exception as e:
            result.error = str(e)[:200]

        if response is not None:
            result.http_status = response.status

        await asyncio.sleep(settle_time_s)
        result.page_load_time_ms = (time.monotonic() - t0) * 1000

        # Capture final URL (detect redirects) — skip on failure to avoid stale page.url
        if not result.timed_out and not result.error:
            try:
                result.final_url = page.url
            except Exception:
                pass

        # Capture browser-side load event timings
        try:
            events = await asyncio.wait_for(
                page.evaluate(LOAD_EVENTS_JS), timeout=5
            )
            if events:
                result.load_events = LoadEvents(**events)
        except Exception:
            pass

        # Verify page rendered content
        try:
            result.content_length = await asyncio.wait_for(
                page.evaluate(CONTENT_CHECK_JS), timeout=5
            )
        except Exception:
            pass

        # Collect page-level structural and resource metrics
        try:
            pm = await asyncio.wait_for(
                page.evaluate(PAGE_METRICS_JS), timeout=5
            )
            if pm:
                result.page_metrics = PageMetrics(
                    dom_element_count=pm.get("dom_element_count", 0),
                    visible_text_length=pm.get("visible_text_length", 0),
                    script_count=pm.get("script_count", 0),
                    stylesheet_count=pm.get("stylesheet_count", 0),
                    image_count=pm.get("image_count", 0),
                    iframe_count=pm.get("iframe_count", 0),
                    anchor_count=pm.get("anchor_count", 0),
                    form_count=pm.get("form_count", 0),
                    resource_count=pm.get("resource_count", 0),
                    total_transfer_bytes=pm.get("total_transfer_bytes", 0),
                    total_decoded_bytes=pm.get("total_decoded_bytes", 0),
                    resources_by_type=pm.get("resources_by_type", {}),
                    document_height=pm.get("document_height", 0),
                    document_width=pm.get("document_width", 0),
                )
        except Exception:
            pass

    except Exception as e:
        result.error = str(e)[:200]
    finally:
        # Stop monitor and collect results
        stop_event.set()
        if monitor_task is not None:
            try:
                result.monitor_result = await asyncio.wait_for(
                    monitor_task, timeout=_CLOSE_TIMEOUT_S
                )
            except (asyncio.TimeoutError, Exception):
                monitor_task.cancel()

        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=_CLOSE_TIMEOUT_S)
            except (asyncio.TimeoutError, Exception):
                pass
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=_CLOSE_TIMEOUT_S)
            except (asyncio.TimeoutError, Exception):
                pass

    return result


async def run_benchmark_reuse(
    page,
    chrome_pid: int,
    url: str,
    mode: str,
    run_index: int,
    sample_interval_s: float,
    settle_time_s: float,
    page_timeout_ms: int,
) -> BenchmarkRun:
    """Run a benchmark on an existing page — browser/context/page stay alive between URLs."""
    result = BenchmarkRun(url=url, mode=mode, run_index=run_index)
    stop_event = asyncio.Event()
    monitor_task = None

    try:
        monitor_task = asyncio.create_task(
            monitor_process_tree(chrome_pid, sample_interval_s, stop_event)
        )

        t0 = time.monotonic()
        response = None
        try:
            response = await page.goto(url, wait_until=config.WAIT_UNTIL, timeout=page_timeout_ms)
        except PwTimeout:
            result.timed_out = True
        except Exception as e:
            result.error = str(e)[:200]

        if response is not None:
            result.http_status = response.status

        await asyncio.sleep(settle_time_s)
        result.page_load_time_ms = (time.monotonic() - t0) * 1000

        if not result.timed_out and not result.error:
            try:
                result.final_url = page.url
            except Exception:
                pass

        try:
            events = await asyncio.wait_for(
                page.evaluate(LOAD_EVENTS_JS), timeout=5
            )
            if events:
                result.load_events = LoadEvents(**events)
        except Exception:
            pass

        try:
            result.content_length = await asyncio.wait_for(
                page.evaluate(CONTENT_CHECK_JS), timeout=5
            )
        except Exception:
            pass

        # Collect page-level structural and resource metrics
        try:
            pm = await asyncio.wait_for(
                page.evaluate(PAGE_METRICS_JS), timeout=5
            )
            if pm:
                result.page_metrics = PageMetrics(
                    dom_element_count=pm.get("dom_element_count", 0),
                    visible_text_length=pm.get("visible_text_length", 0),
                    script_count=pm.get("script_count", 0),
                    stylesheet_count=pm.get("stylesheet_count", 0),
                    image_count=pm.get("image_count", 0),
                    iframe_count=pm.get("iframe_count", 0),
                    anchor_count=pm.get("anchor_count", 0),
                    form_count=pm.get("form_count", 0),
                    resource_count=pm.get("resource_count", 0),
                    total_transfer_bytes=pm.get("total_transfer_bytes", 0),
                    total_decoded_bytes=pm.get("total_decoded_bytes", 0),
                    resources_by_type=pm.get("resources_by_type", {}),
                    document_height=pm.get("document_height", 0),
                    document_width=pm.get("document_width", 0),
                )
        except Exception:
            pass

    except Exception as e:
        result.error = str(e)[:200]
    finally:
        stop_event.set()
        if monitor_task is not None:
            try:
                result.monitor_result = await asyncio.wait_for(
                    monitor_task, timeout=_CLOSE_TIMEOUT_S
                )
            except (asyncio.TimeoutError, Exception):
                monitor_task.cancel()

    return result
