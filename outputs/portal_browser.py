"""Optional browser fallback for the SRun portal.

Only reached when the HTTP path cannot finish the job: the portal demands a
captcha, or it keeps rejecting an otherwise well-formed login. Every platform
runs fine without Playwright -- the caller logs ``BROWSER_UNAVAILABLE`` and waits
for a human instead of failing silently.

Selectors below were confirmed against the live portal on 2026-11-12. They
describe the front end, not the protocol, so a redesign breaks this path and
leaves ``portal_http`` untouched.
"""
from __future__ import annotations
import logging
import urllib.parse

import campus_core

log = logging.getLogger('campus')


def prepare_form(page):
    page.goto(campus_core.PORTAL, wait_until='domcontentloaded', timeout=20000)
    page.locator('.tab-item[data="account"]').wait_for(state='visible', timeout=12000)
    page.locator('.tab-item[data="account"]').click()
    page.locator('#username').wait_for(state='visible')
    page.locator('.domain.custom-select .select-selected').click()
    page.locator('.domain.custom-select .select-items [data-value="@study"]').click()
    if page.locator('select.domain').input_value() != '@study':
        raise RuntimeError('domain_mismatch')
    if page.locator('#captcha').is_visible():
        return False
    if page.locator('#remember').is_checked():
        page.locator('label[for="remember"]').click()
    if page.locator('label[for="protocol"]').is_visible() and not page.locator('#protocol').is_checked():
        page.locator('label[for="protocol"]').click()
    return True


def login_once(stopped, read_credentials, browser_session):
    """``browser_session`` is a context manager yielding a Playwright browser."""
    credentials = read_credentials()
    if not credentials:
        log.warning('CREDENTIALS_MISSING: run setup')
        return False
    host = urllib.parse.urlparse(campus_core.PORTAL).hostname
    with browser_session() as browser:
        try:
            context = browser.new_context(service_workers='block')
            # Never forward credentials to another host; no saved profile, trace
            # or screenshots.
            context.route('**/*', lambda route: route.continue_()
                          if urllib.parse.urlparse(route.request.url).hostname == host
                          else route.abort())
            page = context.new_page()
            page.set_default_timeout(10000)
            if not prepare_form(page):
                log.warning('CAPTCHA_REQUIRED: manual portal login required')
                return False
            if stopped():
                return False
            page.locator('#username').fill(credentials[0])
            page.locator('#password').fill(credentials[1])
            page.locator('#login-account').click()
            for _ in range(6):
                if stopped():
                    return False
                page.wait_for_timeout(2500)
                if campus_core.internet_ok():
                    log.info('LOGIN_VERIFIED')
                    return True
            return False
        finally:
            credentials = None
            browser.close()
