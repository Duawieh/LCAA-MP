"""Playwright session over a locally installed Chromium-based browser.

The HTTP path in ``portal_http`` never needs this module. It exists only for the
case where the portal demands a captcha, and it never downloads anything: it
tries the browsers already on the machine, then a Chromium that the user chose
to install for Playwright. When none of that works the caller gets
``BrowserUnavailable`` and logs it once -- a machine without a browser still
authenticates over HTTP.
"""
from contextlib import contextmanager

from platforms.base import BrowserUnavailable

CHANNELS = ('msedge', 'chrome')


@contextmanager
def browser_session(channels=CHANNELS):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        raise BrowserUnavailable('playwright is not installed')
    with sync_playwright() as playwright:
        browser = None
        for channel in channels:
            try:
                browser = playwright.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        if browser is None:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception:
                raise BrowserUnavailable('no chromium-based browser available')
        try:
            yield browser
        finally:
            browser.close()
