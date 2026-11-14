"""
Gemini integration for the Maison Tisane assistant.

Handles calls to Google Gemini models using the google-genai SDK or direct HTTPS
requests. Fails gracefully with mapped error messages and never leaks API keys.
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger("maison")

# Error message mappings
ERROR_403 = "HTTP 403: key wrong or restricted"
ERROR_404 = "HTTP 404: model name wrong"
ERROR_429 = "HTTP 429: quota exceeded"
ERROR_TIMEOUT = "timed out"


class ModelUnavailable(Exception):
    """The language model could not be reached or gave nothing usable."""
    pass


def model_is_available() -> bool:
    """Return True if both GEMINI_API_KEY and GEMINI_MODEL are set."""
    key = getattr(settings, "GEMINI_API_KEY", "") or ""
    model = getattr(settings, "GEMINI_MODEL", "") or ""
    return bool(key.strip() and model.strip())


def generate_content(prompt: str, system_instruction: str = "") -> str:
    """
    Generate content using Gemini.
    Uses google-genai SDK if available, or direct REST API via HTTPS.
    Never exposes the API key in logs or exceptions.
    """
    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    model = (getattr(settings, "GEMINI_MODEL", "") or "").strip()

    if not api_key:
        raise ModelUnavailable("no API key set")
    if not model:
        raise ModelUnavailable("no model configured")

    timeout = float(getattr(settings, "EXTERNAL_API_TIMEOUT", 3))

    # Try official google-genai SDK first if installed
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=300,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        text = response.text or ""
        if not text.strip():
            raise ModelUnavailable("empty reply")
        return text.strip()

    except ImportError:
        # Fall back to HTTPS REST request
        return _call_rest(api_key, model, prompt, system_instruction, timeout)
    except ModelUnavailable:
        raise
    except Exception as exc:
        err_str = str(exc).lower()
        if "403" in err_str or "permission" in err_str or "unauthorized" in err_str:
            raise ModelUnavailable(ERROR_403) from exc
        if "404" in err_str or "not found" in err_str:
            raise ModelUnavailable(ERROR_404) from exc
        if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
            raise ModelUnavailable(ERROR_429) from exc
        if "timeout" in err_str or "timed out" in err_str or "deadline" in err_str:
            raise ModelUnavailable(ERROR_TIMEOUT) from exc
        # Fallback to REST if SDK had another issue
        return _call_rest(api_key, model, prompt, system_instruction, timeout)


def _call_rest(
    api_key: str, model: str, prompt: str, system_instruction: str, timeout: float
) -> str:
    """Direct HTTPS REST call to Gemini endpoint with header auth."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    body_data = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 300,
            "candidateCount": 1,
        },
    }
    if system_instruction:
        body_data["system_instruction"] = {
            "parts": [{"text": system_instruction}]
        }

    body = json.dumps(body_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "User-Agent": "maison-tisane/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise ModelUnavailable(f"HTTP {response.status}")
            payload = json.loads(response.read(200000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise ModelUnavailable(ERROR_403) from exc
        if exc.code == 404:
            raise ModelUnavailable(ERROR_404) from exc
        if exc.code == 429:
            raise ModelUnavailable(ERROR_429) from exc
        raise ModelUnavailable(f"HTTP {exc.code}") from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
            raise ModelUnavailable(ERROR_TIMEOUT) from exc
        raise ModelUnavailable(f"network unreachable: {exc}") from exc
    except Exception as exc:
        raise ModelUnavailable(f"call failed: {type(exc).__name__}") from exc

    try:
        candidates = payload["candidates"]
        parts = candidates[0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelUnavailable(f"no usable candidate: {type(exc).__name__}") from exc

    if not text:
        raise ModelUnavailable("empty reply")
    return text
