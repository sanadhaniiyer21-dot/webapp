"""
Error code helpers, and the exception reporter filter that keeps secrets off
Django's debug page.
"""

import logging
import re

from django.db import DatabaseError
from django.views.debug import SafeExceptionReporterFilter

log = logging.getLogger("maison")

# Codes the assistant and the error pages refer to by name.
SITE_ASSISTANT_UNAVAILABLE = "SITE-1001"
SITE_WEATHER_SLOW = "SITE-1002"

# HTTP codes we serve our own page for at /error/<code>/.
SERVABLE_CODES = {400, 403, 404, 405, 429, 500, 502, 503, 504}

# Matches a three digit HTTP status, MT-xxx, or one of our SITE-nnnn codes.
# \b on its own would not stop "4041" matching, so the digits are bounded.
CODE_PATTERN = re.compile(r"(?<![\w-])(SITE-\d{4}|MT-\d{3}|[1-5]\d{2})(?![\w-])", re.IGNORECASE)


class WideExceptionReporterFilter(SafeExceptionReporterFilter):
    """
    Django hides settings whose name contains API, KEY, PASS, SECRET, SIGNATURE
    or TOKEN. It does not hide names ending in URI, URL or DSN, so a connection
    string with a password in it was visible on the debug page.

    This widens the list. It only affects the debug page and the error email
    body, never normal operation.
    """

    # Checked as substrings against the upper-cased setting name.
    extra_hidden = ("URI", "URL", "DSN", "TOKEN", "KEY", "SECRET", "PASSWORD", "PASS")

    def is_active(self, request):
        # Always filter, even when DEBUG is on, so a local screen share or a
        # screenshot in a report cannot leak a key.
        return True

    def hidden_settings_match(self, key: str) -> bool:
        upper = key.upper()
        return any(token in upper for token in self.extra_hidden)

    def cleanse_setting(self, key, value):
        if isinstance(key, str) and self.hidden_settings_match(key):
            return self.cleansed_substitute
        return super().cleanse_setting(key, value)


def find_code(text: str) -> str | None:
    """
    Return the first error code mentioned in free text, normalised, or None.

    'what does error 404 mean' -> '404'
    'site-1001?'               -> 'SITE-1001'
    """
    match = CODE_PATTERN.search(text or "")
    if not match:
        return None
    return match.group(1).upper()


def lookup_code(code: str):
    """
    Fetch one ErrorCode row, or None. Never raises: the error pages call this
    and must render even when the database is the thing that is broken.
    """
    from core.models import ErrorCode

    if not code:
        return None
    try:
        return ErrorCode.objects.filter(code=str(code).upper()).first()
    except DatabaseError as exc:
        log.warning("error code lookup failed, database unavailable: %s", exc)
        return None


def all_codes() -> list:
    """Every error code row, or an empty list if the database is unavailable."""
    from core.models import ErrorCode

    try:
        return list(ErrorCode.objects.all())
    except DatabaseError as exc:
        log.warning("error code listing failed, database unavailable: %s", exc)
        return []


def static_fallback(code) -> dict:
    """
    A minimal explanation that needs no database at all.

    The 500 page uses this: if the database is what failed, reading ErrorCode
    to explain the failure would fail too.
    """
    text = {
        400: ("Bad Request", "The site could not read what was sent."),
        403: ("Forbidden", "This is not yours to see, or a form's security check expired."),
        404: ("Not Found", "There is nothing at this address."),
        405: ("Method Not Allowed", "This address does not accept that kind of request."),
        429: ("Too Many Requests", "Too many requests arrived at once. Wait a minute."),
        500: ("Internal Server Error", "Something broke on our side while building this page."),
        502: ("Bad Gateway", "The server in front of the site got no sensible answer from it."),
        503: ("Service Unavailable", "A part the site depends on is not answering."),
        504: ("Gateway Timeout", "The site took too long to answer."),
    }
    try:
        number = int(code)
    except (TypeError, ValueError):
        number = 500
    title, meaning = text.get(number, ("Error", "Something went wrong."))
    return {"code": str(number), "title": title, "meaning": meaning}
