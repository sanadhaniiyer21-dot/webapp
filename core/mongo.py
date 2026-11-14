"""
MongoDB for chat transcripts, thumbs up/down feedback, user profiles
and user events.

Design rules, in order of importance:

1. MongoDB is optional. If MONGODB_URI is empty or the server is unreachable,
   the site works exactly as before and only logging is skipped.
2. A dead database must never slow a request down. The client uses a short
   server selection timeout, and after any failure a circuit breaker skips
   Mongo entirely for 30 seconds rather than paying that timeout per request.
3. No raw IP addresses, email addresses or password hashes are written here.
   The IP is hashed with HMAC-SHA256 keyed by SECRET_KEY, which makes it
   useful for counting abuse and useless for identifying a person.
"""

import hashlib
import hmac
import logging
import re
import threading
import time
from datetime import datetime, timezone

from django.conf import settings

log = logging.getLogger("maison")

CHAT_LOGS = "chat_logs"
FEEDBACK = "feedback"
USERS = "users"
USER_EVENTS = "user_events"

# Module state, guarded because gunicorn serves requests on threads.
_lock = threading.Lock()
_client = None
_breaker_open_until = 0.0
_indexes_ensured = False
_no_uri_warned = False


def is_configured() -> bool:
    return bool(getattr(settings, "MONGODB_URI", ""))


_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact(text: str) -> str:
    """
    Remove email addresses from text before it is stored.

    Needed because an address can arrive in text we did not expect it in. When
    the assistant opens a ticket it writes "We will reply to you@example.com"
    into its own reply, and that reply is logged here. The rule is that no
    address reaches this database, so the rule is enforced at the point of
    writing rather than trusted to every caller.

    The address is still kept in the SQL Ticket row, where it is needed to
    answer the person.
    """
    return _EMAIL_PATTERN.sub("[email removed]", text or "")


def hash_ip(ip: str) -> str:
    """
    One-way, keyed hash of a client IP. HMAC-SHA256 with SECRET_KEY as the
    key, returned as hex. Cannot be reversed with a rainbow table.
    """
    if not ip:
        return ""
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256
    )
    return digest.hexdigest()


def _timeout_ms() -> int:
    """Timeout in milliseconds derived from EXTERNAL_API_TIMEOUT."""
    return int(float(getattr(settings, "EXTERNAL_API_TIMEOUT", 3)) * 1000)


def _breaker_is_open() -> bool:
    return time.monotonic() < _breaker_open_until


def _trip_breaker(reason: str) -> None:
    global _breaker_open_until, _client
    seconds = int(getattr(settings, "MONGODB_BREAKER_SECONDS", 30))
    _breaker_open_until = time.monotonic() + seconds
    # Drop the client so the next attempt after the breaker closes reconnects.
    _client = None
    log.warning(
        "mongodb unavailable, skipping writes for %ss: %s",
        seconds,
        reason,
    )


def reset() -> None:
    """Close the client and clear the breaker. Used by tests and check_setup."""
    global _client, _breaker_open_until, _indexes_ensured
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001 - closing must never raise upward
                pass
        _client = None
        _breaker_open_until = 0.0
        _indexes_ensured = False


def _ensure_indexes(db) -> None:
    """Create indexes idempotently on first successful connection."""
    global _indexes_ensured
    if _indexes_ensured:
        return
    try:
        from pymongo import ASCENDING, DESCENDING, IndexModel

        # chat_logs
        db[CHAT_LOGS].create_indexes([
            IndexModel([("message_id", ASCENDING)], unique=True, name="ix_message_id"),
            IndexModel([("session_id", ASCENDING)], name="ix_session_id"),
            IndexModel([("ts", DESCENDING)], name="ix_ts"),
        ])
        # feedback
        db[FEEDBACK].create_indexes([
            IndexModel(
                [("message_id", ASCENDING), ("session_id", ASCENDING)],
                unique=True,
                name="ix_msg_session",
            ),
            IndexModel([("ts", DESCENDING)], name="ix_ts"),
        ])
        # users
        db[USERS].create_indexes([
            IndexModel([("user_id", ASCENDING)], unique=True, name="ix_user_id"),
        ])
        # user_events
        db[USER_EVENTS].create_indexes([
            IndexModel([("user_id", ASCENDING)], name="ix_user_id"),
            IndexModel([("ts", DESCENDING)], name="ix_ts"),
            IndexModel([("event", ASCENDING)], name="ix_event"),
        ])
        _indexes_ensured = True
    except Exception as exc:  # noqa: BLE001
        log.warning("mongodb index creation failed: %s", exc)


def get_client():
    """
    A shared MongoClient, or None if Mongo is unconfigured, broken or inside
    the breaker window. Never raises.
    """
    global _client, _no_uri_warned

    if not is_configured():
        if not _no_uri_warned:
            log.warning("MONGODB_URI is empty; all MongoDB helpers are no-ops")
            _no_uri_warned = True
        return None

    if _breaker_is_open():
        return None

    with _lock:
        if _client is not None:
            return _client
        try:
            from pymongo import MongoClient

            timeout_ms = _timeout_ms()
            _client = MongoClient(
                settings.MONGODB_URI,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=timeout_ms,
                appname="maison-tisane",
            )
            # Ensure indexes on the database
            _ensure_indexes(_client[settings.MONGODB_DB])
            return _client
        except Exception as exc:  # noqa: BLE001 - any driver error is "unavailable"
            _trip_breaker(f"client creation failed: {type(exc).__name__}")
            return None


def get_collection(name: str):
    """One collection handle, or None. Never raises."""
    client = get_client()
    if client is None:
        return None
    try:
        return client[settings.MONGODB_DB][name]
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(f"collection access failed: {type(exc).__name__}")
        return None


def ping() -> tuple[bool, str]:
    """
    Used by /health/ and check_setup. Returns (ok, detail).

    Deliberately ignores the breaker so the Status page reports what is true
    now rather than what was true up to 30 seconds ago.
    """
    global _breaker_open_until

    if not is_configured():
        return False, "not configured"

    with _lock:
        _breaker_open_until = 0.0

    client = get_client()
    if client is None:
        return False, "client unavailable"
    try:
        client.admin.command("ping")
        return True, "reachable"
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        _trip_breaker(detail)
        return False, detail[:300]


def _insert(collection_name: str, document: dict) -> bool:
    """
    Write one document. Returns whether it was written, and never raises.
    """
    try:
        collection = get_collection(collection_name)
        if collection is None:
            return False
        collection.insert_one(document)
        return True
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(f"insert into {collection_name} failed: {type(exc).__name__}")
        return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log_chat(
    *,
    message_id: str,
    session_id: str,
    page: str,
    user_message: str,
    reply: str,
    source: str,
    ticket_id=None,
    latency_ms: int = 0,
    ip: str = "",
    user_id: int | None = None,
) -> bool:
    """
    Record one exchange. Returns True if it was written.

    No email address is stored: if a visitor gave one it went into the SQL
    ticket, where it is needed to reply, and nowhere else.
    """
    result = _insert(
        CHAT_LOGS,
        {
            "message_id": message_id,
            "session_id": session_id,
            "ts": now_utc(),
            "page": page,
            # Both are redacted: an address can appear in what the visitor
            # typed and in what the assistant wrote back.
            "user_message": redact(user_message)[:2000],
            "reply": redact(reply)[:4000],
            "source": source,
            "ticket_id": ticket_id,
            "latency_ms": latency_ms,
            "ip_hash": hash_ip(ip),
            "user_id": user_id,
        },
    )
    # Increment chat_count on the user doc if logged in
    if user_id is not None:
        _inc_user_counter(user_id, "chat_count")
    return result


def save_feedback(
    *,
    message_id: str,
    session_id: str,
    value: str,
    page: str,
    user_id: int | None = None,
) -> bool:
    """
    Record a thumbs up or down. Upserts: one vote per message per session,
    last vote wins. Returns True if it was written.
    """
    try:
        collection = get_collection(FEEDBACK)
        if collection is None:
            return False
        collection.update_one(
            {"message_id": message_id, "session_id": session_id},
            {
                "$set": {
                    "ts": now_utc(),
                    "value": value,
                    "page": page,
                    "user_id": user_id,
                }
            },
            upsert=True,
        )
        if user_id is not None:
            _inc_user_counter(user_id, "feedback_count")
        return True
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(f"feedback upsert failed: {type(exc).__name__}")
        return False


def upsert_user(user) -> bool:
    """
    Create or update a user document in MongoDB. Called by signals.
    NO email, NO password hash stored.
    """
    try:
        collection = get_collection(USERS)
        if collection is None:
            return False
        collection.update_one(
            {"user_id": user.pk},
            {
                "$set": {
                    "user_id": user.pk,
                    "username": user.username,
                    "date_joined": user.date_joined,
                    "last_login": user.last_login,
                    "is_staff": user.is_staff,
                    "updated_at": now_utc(),
                },
                "$setOnInsert": {
                    "preferences": {},
                    "chat_count": 0,
                    "feedback_count": 0,
                },
            },
            upsert=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(f"user upsert failed: {type(exc).__name__}")
        return False


def log_user_event(
    user_id: int | None,
    event: str,
    ip: str = "",
    session_id: str | None = None,
    extra: dict | None = None,
) -> bool:
    """
    Log a user event (signup, login, logout, subscribe, ticket_created,
    feedback). Never stores email or raw IP.
    """
    doc = {
        "user_id": user_id,
        "session_id": session_id,
        "ts": now_utc(),
        "event": event,
        "ip_hash": hash_ip(ip),
        "extra": extra or {},
    }
    return _insert(USER_EVENTS, doc)


def _inc_user_counter(user_id: int, field: str) -> None:
    """Increment a counter on the user document. Best effort."""
    try:
        collection = get_collection(USERS)
        if collection is not None:
            collection.update_one(
                {"user_id": user_id},
                {"$inc": {field: 1}, "$set": {"updated_at": now_utc()}},
            )
    except Exception:  # noqa: BLE001
        pass


# Keep backwards compat for existing code that calls log_feedback
def log_feedback(*, message_id: str, session_id: str, value: str, page: str) -> bool:
    """Legacy wrapper for save_feedback."""
    return save_feedback(
        message_id=message_id,
        session_id=session_id,
        value=value,
        page=page,
    )


def counts() -> dict:
    """Document counts for the Status page. Zeroes if Mongo is unavailable."""
    result = {"chat_logs": 0, "feedback": 0, "users": 0, "user_events": 0}
    client = get_client()
    if client is None:
        return result
    try:
        database = client[settings.MONGODB_DB]
        for name in result:
            result[name] = database[name].estimated_document_count()
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(f"count failed: {type(exc).__name__}")
    return result
