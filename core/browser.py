"""Shared Playwright browser launch helpers.

Provides a single place for the launch → context → page → close pattern
that is otherwise duplicated across every investigation script.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from . import config

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


async def launch_browser(
    pw: Playwright,
    mode: str,
    *,
    viewport: dict | None = None,
    user_agent: str | None = None,
    extra_args: list[str] | None = None,
    ignore_https_errors: bool = True,
    color_scheme: str | None = None,
    reduced_motion: str | None = None,
) -> tuple[Browser, BrowserContext, Page]:
    """Launch a browser in the given mode and return (browser, context, page).

    Parameters
    ----------
    pw : Playwright instance
    mode : One of the keys in ``config.MODE_PARAMS``
    viewport : Override default viewport
    user_agent : Override user-agent (headless modes default to spoofed headful UA)
    extra_args : Extra Chromium flags
    ignore_https_errors : Pass through to ``browser.new_context``
    color_scheme, reduced_motion : Optional context overrides for matched profiles
    """
    channel, headless = config.MODE_PARAMS[mode]
    args = list(config.BROWSER_ARGS)
    if extra_args:
        args.extend(extra_args)

    browser = await pw.chromium.launch(
        headless=headless,
        channel=channel,
        args=args,
    )

    ctx_kwargs: dict = {"ignore_https_errors": ignore_https_errors}

    # Spoof user-agent in headless modes so UA alone isn't a signal
    if headless and user_agent is None and config.CHROME_USER_AGENT:
        ctx_kwargs["user_agent"] = config.CHROME_USER_AGENT
    elif user_agent is not None:
        ctx_kwargs["user_agent"] = user_agent

    if viewport is not None:
        ctx_kwargs["viewport"] = viewport
    if color_scheme is not None:
        ctx_kwargs["color_scheme"] = color_scheme
    if reduced_motion is not None:
        ctx_kwargs["reduced_motion"] = reduced_motion

    context = await browser.new_context(**ctx_kwargs)
    page = await context.new_page()
    return browser, context, page


async def close_all(
    browser: Browser,
    context: BrowserContext,
    page: Page,
) -> None:
    """Close page, context, and browser in order."""
    await page.close()
    await context.close()
    await browser.close()


async def detect_chrome_ua(pw: Playwright) -> str:
    """Launch headful Chrome, read its real user-agent, and close.

    The result is also stored in ``config.CHROME_USER_AGENT`` for later use.
    """
    browser = await pw.chromium.launch(
        headless=False,
        channel=config.CHANNEL,
        args=config.BROWSER_ARGS,
    )
    ctx = await browser.new_context()
    page = await ctx.new_page()
    ua = await page.evaluate("navigator.userAgent")
    await browser.close()
    config.CHROME_USER_AGENT = ua
    return ua


# ---------------------------------------------------------------------------
# Probe-server session helpers (used by experiments/investigations)
# ---------------------------------------------------------------------------

async def create_session(
    client: httpx.AsyncClient,
    mode: str,
    profile: str = "default",
    page: str = "",
    *,
    base_url: str | None = None,
) -> str:
    """Create a new session on the probe server and return the session_id."""
    url = (base_url or config.BASE_URL) + "/session/new"
    resp = await client.get(url, params={"mode": mode, "profile": profile, "page": page})
    resp.raise_for_status()
    return resp.json()["session_id"]


async def get_results(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    base_url: str | None = None,
) -> list[dict]:
    """Fetch all request records for a session from the probe server."""
    url = (base_url or config.BASE_URL) + f"/results/{session_id}"
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()["requests"]


async def get_resources(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    base_url: str | None = None,
) -> list[str]:
    """Fetch just the resource names for a session."""
    reqs = await get_results(client, session_id, base_url=base_url)
    return [r["resource"] for r in reqs]
