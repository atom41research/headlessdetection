---
layout: default
title: User-Agent
parent: Detection Methods
nav_order: 4
---

# User-Agent Detection

Chrome headless announces itself in the `user-agent` HTTP header by including `HeadlessChrome` instead of `Chrome` in the browser token.

## The signal

| Header | Headful | Headless |
|---|---|---|
| `user-agent` | `Chrome/144.0.0.0` | `HeadlessChrome/144.0.0.0` |
| `sec-ch-ua` | `"Google Chrome";v="144"` | `"Google Chrome";v="144"` |

The `user-agent` header is the only HTTP header that differs between headful and headless Chrome. All Client Hints headers (`sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform`) are identical.

## Detection

Server-side: check whether the `user-agent` header string contains `HeadlessChrome`.

Client-side: check `navigator.userAgent` for the same substring.

```javascript
if (navigator.userAgent.includes('HeadlessChrome')) {
  // headless mode detected
}
```

This is 100% reliable **if the user-agent has not been modified**.

## Spoofability

**Trivial.** Playwright, Puppeteer, and Selenium all provide built-in APIs to override the user-agent string:

- Playwright: `browser.new_context(user_agent="...")`
- Puppeteer: `page.setUserAgent("...")`
- Selenium: Chrome launch argument `--user-agent=...`

The `sec-ch-ua` Client Hints header is set by the browser engine and is harder to override, but it can still be modified via Chrome DevTools Protocol (`Network.setUserAgentOverride`). In practice, all major automation frameworks set both headers when a custom user-agent is configured.

## Why this is documented

The user-agent signal is included for completeness. Any serious automation setup overrides the user-agent string as a first step, making this detection mechanism useless against intentional evasion. It remains useful only for detecting naive automation scripts that do not customize the user-agent.

For robust detection, rely on [scrollbar width](scrollbar-width.md), [window chrome gap](window-chrome.md), or [rendering stress timing](rendering-stress.md) instead.
