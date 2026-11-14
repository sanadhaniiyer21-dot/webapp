"""
Request logging, and turning a database outage into an honest 503.
"""

import logging
import time
import uuid

from django.db import InterfaceError, OperationalError

log = logging.getLogger("requests")

SKIP_PREFIXES = ("/static/",)


def client_ip(request) -> str:
    """
    The visitor's address, trusting Render's proxy header first.

    Only the left-most entry of X-Forwarded-For is the client; the rest are
    proxies. On a host that does not set the header this falls back to
    REMOTE_ADDR.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def truncate_ip(ip: str) -> str:
    """
    An address with its last group removed, for the log line.

    198.51.100.42 becomes 198.51.100.x. Enough to spot one noisy source,
    not enough to identify a person. The full address is never logged.
    """
    if not ip:
        return "-"
    if ":" in ip:  # IPv6
        parts = ip.split(":")
        return ":".join(parts[:4]) + "::x" if len(parts) > 4 else ip
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".x"
    return "-"


class RequestLogMiddleware:
    """
    One log line per request, and a safety net for database failures.

    Sits outermost in MIDDLEWARE so the duration it reports is the whole
    request, and so it still logs responses produced by middleware below it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = uuid.uuid4().hex[:12]
        request.request_id = request_id

        if request.path.startswith(SKIP_PREFIXES):
            return self.get_response(request)

        started = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - started) * 1000

        log.info(
            "%s %s %s %s %.1fms ip=%s",
            request_id,
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
            truncate_ip(client_ip(request)),
        )
        response["X-Request-ID"] = request_id
        return response

    def process_exception(self, request, exception):
        """
        A database outage is a 503, not a 500.

        A 500 says "we have a bug". A 503 says "a part we depend on is not
        answering", which is the truth when Postgres is unreachable, and it is
        what the Status page will also be reporting.
        """
        if not isinstance(exception, (OperationalError, InterfaceError)):
            return None

        log.error(
            "%s %s %s database unavailable: %s: %s",
            getattr(request, "request_id", "-"),
            request.method,
            request.get_full_path(),
            type(exception).__name__,
            exception,
        )

        # Imported here to avoid a circular import at startup.
        from core.views import service_unavailable

        return service_unavailable(request)
