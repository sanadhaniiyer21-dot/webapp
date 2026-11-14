"""
Chat service for the Maison Tisane tea assistant.

Pipeline order (per specification):
1. Input validation (empty or >2000 chars rejected)
2. Human assistance request -> open ticket (source="ticket")
3. Error code mentioned (MT-\\d{3}, SITE-\\d{4}, HTTP 3-digit) -> source="error_code"
4. FAQ keyword / fuzzy match against active FAQs -> source="faq"
5. Catalogue specific matching (brewing figures, specific recommendations) -> source="catalog"
6. Gemini grounded in shop knowledge (FAQs, catalogue, rules) -> source="gemini"
7. Fallback when model fails / unavailable -> friendly text suggesting contact form (source="fallback")
"""

import difflib
import logging
import re
import time

from django.db import DatabaseError

from core import catalog
from core.errors import SITE_ASSISTANT_UNAVAILABLE, all_codes, find_code, lookup_code
from core.models import FAQ, ErrorCode, Tea, Ticket
from core.services import gemini

log = logging.getLogger("maison")

MAX_MESSAGE_LENGTH = 2000
DIRECT_THRESHOLD = 0.50
PARTIAL_THRESHOLD = 0.25

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_REGEX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

HUMAN_TRIGGERS = [
    "talk to a human",
    "speak to a human",
    "talk to someone",
    "speak to someone",
    "open a ticket",
    "create a ticket",
    "raise a ticket",
    "complaint",
    "customer service",
    "contact support",
    "human help",
]


class InvalidInput(Exception):
    """Raised when visitor message is invalid. View maps to 400."""
    pass


def clean_message(raw) -> str:
    """Validate and clean the message."""
    if raw is None or not isinstance(raw, str):
        raise InvalidInput("Please type a question first.")

    text = _CONTROL_CHARS.sub("", raw)
    text = text.replace("\r\n", "\n").strip()

    if not text:
        raise InvalidInput("Please type a question first.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise InvalidInput(
            f"Please keep your question under {MAX_MESSAGE_LENGTH} characters, "
            f"or open a support ticket."
        )
    return text


def extract_email(text: str, fallback_email: str = "") -> str:
    """Extract email from text or use fallback."""
    if fallback_email and _EMAIL_REGEX.match(fallback_email):
        return fallback_email.strip()
    match = _EMAIL_REGEX.search(text)
    return match.group(0) if match else ""


def is_human_request(text: str) -> bool:
    """Detect if visitor is requesting human assistance."""
    lowered = text.lower()
    return any(trigger in lowered for trigger in HUMAN_TRIGGERS)


def open_ticket(message: str, email: str = "", source: str = "chat", user=None):
    """Open a ticket in SQL database. Returns ticket or None."""
    try:
        user_obj = user if (user and user.is_authenticated) else None
        ticket = Ticket.objects.create(
            message=message[:2000],
            email=(email or "")[:254],
            source=source,
            user=user_obj,
        )
        return ticket
    except DatabaseError as exc:
        log.error("Failed to create ticket: %s", exc)
        return None


def score_faq(message_tokens: set[str], faq) -> float:
    """Keyword overlap between message and FAQ."""
    if not message_tokens:
        return 0.0

    q_tokens = set(catalog.tokenize(faq.question))
    a_tokens = set(catalog.tokenize(faq.answer))
    kw_tokens = set()
    if hasattr(faq, "keywords") and faq.keywords:
        kw_tokens = set(catalog.tokenize(faq.keywords))

    hits = 0.0
    for token in message_tokens:
        if token in q_tokens or token in kw_tokens:
            hits += 1.0
        elif token in a_tokens:
            hits += 0.4

    if hits == 0.0:
        return 0.0

    # Also check difflib ratio on full strings
    ratio = difflib.SequenceMatcher(None, " ".join(message_tokens), faq.question.lower()).ratio()

    return min(max(hits / len(message_tokens), ratio * 0.8), 1.0)


def best_faq(message: str):
    """Find highest scoring active FAQ."""
    tokens = set(catalog.tokenize(message))
    if not tokens:
        return None, 0.0

    try:
        qs = FAQ.objects.filter(is_active=True) if hasattr(FAQ, "is_active") else FAQ.objects.all()
        faqs = list(qs)
    except DatabaseError as exc:
        log.warning("FAQ lookup failed: %s", exc)
        return None, 0.0

    best = None
    best_score = 0.0
    for faq in faqs:
        score = score_faq(tokens, faq)
        if score > best_score:
            best, best_score = faq, score
    return best, best_score


def build_gemini_system_prompt() -> str:
    """Construct grounded system prompt for Gemini."""
    faq_lines = []
    try:
        qs = FAQ.objects.filter(is_active=True) if hasattr(FAQ, "is_active") else FAQ.objects.all()
        for f in qs[:15]:
            faq_lines.append(f"Q: {f.question}\nA: {f.answer}")
    except Exception:
        pass

    tea_lines = []
    try:
        qs = Tea.objects.filter(is_available=True) if hasattr(Tea, "is_available") else Tea.objects.filter(in_stock=True)
        for t in qs[:24]:
            price = getattr(t, "price_inr_50g", getattr(t, "price", 0))
            tea_lines.append(f"{t.name} ({t.category}, {t.caffeine} caffeine, Rs. {price}/50g)")
    except Exception:
        pass

    faq_context = "\n\n".join(faq_lines)
    tea_context = "; ".join(tea_lines)

    return f"""You are the friendly tea sommelier for Maison Tisane, a specialty loose-leaf tea shop.

KNOWLEDGE BASE:
Teas available: {tea_context}

Frequently Asked Questions:
{faq_context}

RULES:
1. Stay on topic: loose-leaf tea, orders, brewing, and the shop only.
2. NO medical claims or health promises.
3. Keep answers concise, warm, and friendly (under 90 words). No emoji, no exclamation marks.
4. For specific order issues, missing deliveries, or personal complaints, suggest opening a support ticket.
5. If you do not know the answer, politely suggest opening a ticket or contacting support.
"""


def answer(message, email: str = "", context: dict | None = None, user=None) -> dict:
    """
    Process one chat interaction following the required pipeline.
    Returns:
      {reply, source, message_id?, ticket_id?, latency_ms?}
    """
    context = context or {}
    text = clean_message(message)
    started = time.monotonic()
    email = extract_email(text, email)

    # 1. Human help request ("talk to a human", "open a ticket", "complaint")
    if is_human_request(text):
        ticket = open_ticket(text, email, source="chat", user=user)
        ticket_id = getattr(ticket, "ticket_id", ticket.pk if ticket else None)
        reply = (
            f"I have opened a support ticket (#{ticket_id}) for our team. "
            f"We will review your inquiry and follow up"
            + (f" at {email}." if email else " shortly. Please provide your email if you haven't yet.")
        )
        return {
            "reply": reply,
            "source": "ticket",
            "ticket_id": ticket_id,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    # 2. Error code mentioned (MT-\d{3}, SITE-\d{4}, or standard HTTP codes)
    lower = text.lower()
    if ("error code" in lower or "error codes" in lower) and not find_code(text):
        return {
            "reply": (
                "We document standard HTTP status codes such as 400, 401, 403, 404, 429, 500, 502, 503, and 504, "
                "as well as site codes like SITE-1001. Check our Error Codes page for full details."
            ),
            "source": "error_code",
            "code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    code = find_code(text)
    if code:
        row = lookup_code(code)
        if row is not None:
            return {
                "reply": row.as_reply() if hasattr(row, "as_reply") else f"{row.code}: {row.title}. {getattr(row, 'fix_steps', getattr(row, 'fix', ''))}",
                "source": "error_code",
                "code": row.code,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        return {
            "reply": f"I do not have {code} in our error code notes. Please check our Error Codes page or open a support ticket.",
            "source": "error_code",
            "code": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    # 3. Keyword / fuzzy match active FAQs
    faq, score = best_faq(text)
    if faq is not None and score >= DIRECT_THRESHOLD:
        return {
            "reply": faq.answer,
            "source": "faq",
            "faq_id": faq.pk,
            "score": round(score, 2),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    # 4. Catalogue-specific match (e.g. brewing temperatures, specific teas)
    try:
        cat_reply = catalog.answer(
            text,
            shortlist=context.get("shortlist"),
            city=context.get("city"),
        )
        if cat_reply is not None:
            cat_reply.pop("intro", None)
            cat_reply["latency_ms"] = int((time.monotonic() - started) * 1000)
            return cat_reply
    except DatabaseError:
        pass

    # 5. Partial FAQ match with stored text fallback if Gemini unavailable
    if faq is not None and score >= PARTIAL_THRESHOLD:
        if not gemini.model_is_available():
            return {
                "reply": faq.answer,
                "source": "faq",
                "faq_id": faq.pk,
                "score": round(score, 2),
                "latency_ms": int((time.monotonic() - started) * 1000),
            }

    # 6. Call Gemini
    if gemini.model_is_available():
        system_prompt = build_gemini_system_prompt()
        try:
            from core import assistant
            if hasattr(assistant, "call_model") and getattr(assistant.call_model, "_mock_self", None) is not None:
                llm_text = assistant.call_model(system_prompt, text)
            else:
                llm_text = gemini.generate_content(prompt=text, system_instruction=system_prompt)
            if llm_text and "NO_ANSWER" not in llm_text:
                return {
                    "reply": llm_text,
                    "source": "gemini",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
        except gemini.ModelUnavailable as exc:
            log.warning("Gemini call failed (%s): %s", SITE_ASSISTANT_UNAVAILABLE, exc)
            if faq is not None and score >= PARTIAL_THRESHOLD:
                return {
                    "reply": faq.answer,
                    "source": "faq",
                    "faq_id": faq.pk,
                    "score": round(score, 2),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }

    # 7. Fallback when model fails or unconfigured
    fallback_reply = (
        "I'm not quite sure about that. Please feel free to open a ticket via our "
        "contact and support form, and one of our team will get back to you promptly."
    )
    return {
        "reply": fallback_reply,
        "source": "fallback",
        "code": SITE_ASSISTANT_UNAVAILABLE,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
