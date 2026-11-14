"""
The tea sommelier assistant wrapper.
Delegates to core.services.chat and core.services.gemini.
Maintains backwards compatibility for tests and existing views.
"""

from django.conf import settings

from core.services import chat, gemini
from core.services.chat import (
    DIRECT_THRESHOLD,
    PARTIAL_THRESHOLD,
    InvalidInput,
    best_faq,
    clean_message,
    open_ticket,
    score_faq,
)
from core.services.gemini import (
    ERROR_403,
    ERROR_404,
    ERROR_429,
    ERROR_TIMEOUT,
    ModelUnavailable,
    model_is_available,
)

NO_MODEL_THRESHOLD = 0.34
NO_ANSWER = "NO_ANSWER"


def call_model(context_text: str, user_message: str) -> str:
    """Wrapper around gemini service for tests and legacy callers."""
    prompt = f"CONTEXT:\n{context_text}\n\nUSER MESSAGE:\n{user_message}"
    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    model = (getattr(settings, "GEMINI_MODEL", "") or "").strip() or "gemini-2.0-flash"
    if not api_key:
        raise ModelUnavailable("no API key set")
    timeout = float(getattr(settings, "EXTERNAL_API_TIMEOUT", 3))
    return gemini._call_rest(api_key, model, prompt, "", timeout)


def answer(message, email: str = "", context: dict | None = None, user=None) -> dict:
    """Delegate to core.services.chat.answer."""
    return chat.answer(message=message, email=email, context=context, user=user)
