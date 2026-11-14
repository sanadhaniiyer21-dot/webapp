"""
Views for Maison Tisane.

Includes:
  1. Helpers (error shape, rate limiting, token auth, CSRF)
  2. Public HTML Pages (home, teas, tea_detail, brew, journal, faq, error_codes, support)
  3. Error pages and handlers (400, 403, 404, 500, 503)
  4. Service worker and offline views
  5. JSON REST API (/api/...)
  6. Accounts & health checks
"""

import hmac
import json
import logging
import time
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, IntegrityError, connection
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie

from core import catalog, mongo
from core.content import JOURNAL
from core.errors import SERVABLE_CODES, all_codes, static_fallback
from core.middleware import client_ip
from core.models import FAQ, BrewPlan, ErrorCode, Favourite, Subscriber, Tea, Ticket
from core.services import chat as chat_service
from core.services import weather as weather_service

weather_module = weather_service

log = logging.getLogger("maison")


# ==========================================================================
# 1. Helpers
# ==========================================================================


def json_error(message: str, code, status: int) -> JsonResponse:
    """One consistent error shape: {"error": ..., "code": ...}."""
    return JsonResponse({"error": message, "code": str(code)}, status=status)


def method_not_allowed(allowed) -> JsonResponse:
    response = json_error("Method not allowed.", 405, 405)
    response["Allow"] = ", ".join(allowed)
    return response


def read_json(request) -> dict:
    """Parse a JSON request body. Raises ValueError with a readable message."""
    if not request.body:
        raise ValueError("Send a JSON body.")
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("That was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object.")
    return payload


def rate_limited(request, bucket: str, limit: int, window: int = 60, session_id: str = ""):
    """
    Fixed-window counter per client ip_hash + session in cache.
    Returns 429 response if over limit, else None.
    """
    ip_raw = client_ip(request) or "unknown"
    ip_h = mongo.hash_ip(ip_raw) or "unknown"
    sess = session_id or getattr(request, "session", {}).get("session_key", "") or "global"

    window_start = int(time.time()) // window
    key = f"ratelimit:{bucket}:{ip_h[:16]}:{sess}:{window_start}"

    try:
        count = cache.get_or_set(key, 0, window + 5)
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window + 5)
        count = 1

    if count > limit:
        retry_after = window - (int(time.time()) % window)
        response = json_error(
            "Too many requests. Please wait a moment and try again.", 429, 429
        )
        response["Retry-After"] = str(max(retry_after, 1))
        return response
    return None


def staff_token_error(request):
    """
    Check the bearer token against TICKET_API_TOKEN using hmac.compare_digest.
    Missing, invalid format or non-matching token -> 401.
    """
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header:
        return json_error("Authentication required. Send a bearer token.", 401, 401)

    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented.strip():
        return json_error("Authentication required. Send a bearer token.", 401, 401)

    expected = getattr(settings, "TICKET_API_TOKEN", "") or ""
    if not expected:
        log.warning("Staff endpoint denied: TICKET_API_TOKEN not configured")
        return json_error("Staff access is not configured on this server.", 401, 401)

    if not hmac.compare_digest(presented.strip(), expected.strip()):
        return json_error("Invalid or expired bearer token.", 401, 401)

    return None


def wants_json(request) -> bool:
    return request.path.startswith("/api/")


# ==========================================================================
# 2. Pages
# ==========================================================================


def home(request):
    weather = weather_service.for_city(request.GET.get("city"))
    suggested = []
    try:
        suggested = list(
            Tea.objects.filter(
                category__in=weather.get("categories") or [], in_stock=True
            )[:3]
        )
        if not suggested:
            suggested = list(Tea.objects.filter(in_stock=True)[:3])
        featured = Tea.objects.filter(slug="oriental-beauty-bai-hao").first()
        categories = _category_summary()
    except DatabaseError:
        featured = None
        categories = []

    return render(
        request,
        "core/home.html",
        {
            "weather": weather,
            "suggested": suggested,
            "featured": featured,
            "categories": categories,
            "page_title": "Loose-leaf tea, explained plainly",
            "meta_description": (
                "An independent loose-leaf tea house. Realistic teas and tisanes, "
                "honest brewing instructions, and an AI assistant grounded in our catalogue."
            ),
        },
    )


def _category_summary() -> list[dict]:
    labels = dict(Tea.CATEGORY_CHOICES)
    summary = []
    for key, label in Tea.CATEGORY_CHOICES:
        teas = list(Tea.objects.filter(category=key)[:1])
        count = Tea.objects.filter(category=key).count()
        if not count:
            continue
        summary.append(
            {
                "key": key,
                "label": labels.get(key, label),
                "count": count,
                "example": teas[0] if teas else None,
            }
        )
    return summary


def teas(request):
    queryset = Tea.objects.filter(is_available=True) if hasattr(Tea, "is_available") else Tea.objects.all()
    selected = {
        "category": request.GET.get("category", ""),
        "caffeine": request.GET.get("caffeine", ""),
        "mood": request.GET.get("mood", ""),
        "q": request.GET.get("q", "").strip(),
    }

    valid_categories = {key for key, _ in Tea.CATEGORY_CHOICES}
    valid_caffeine = {key for key, _ in Tea.CAFFEINE_CHOICES}

    if selected["category"] in valid_categories:
        queryset = queryset.filter(category=selected["category"])
    if selected["caffeine"] in valid_caffeine:
        queryset = queryset.filter(caffeine=selected["caffeine"])
    if selected["mood"] in Tea.MOOD_CHOICES:
        queryset = queryset.filter(moods__icontains=selected["mood"])
    if selected["q"]:
        from django.db.models import Q
        term = selected["q"]
        queryset = queryset.filter(
            Q(name__icontains=term)
            | Q(flavour_notes__icontains=term)
            | Q(origin__icontains=term)
            | Q(description__icontains=term)
        )

    return render(
        request,
        "core/teas.html",
        {
            "teas": list(queryset),
            "selected": selected,
            "categories": Tea.CATEGORY_CHOICES,
            "caffeine_levels": Tea.CAFFEINE_CHOICES,
            "moods": Tea.MOOD_CHOICES,
            "page_title": "Teas",
            "meta_description": "Our complete selection of single-origin loose-leaf teas and botanicals.",
        },
    )


def tea_detail(request, slug):
    tea = get_object_or_404(Tea, slug=slug)
    related = list(
        Tea.objects.filter(category=tea.category).exclude(pk=tea.pk)[:3]
    )
    is_favourite = False
    if request.user.is_authenticated:
        is_favourite = Favourite.objects.filter(user=request.user, tea=tea).exists()

    return render(
        request,
        "core/tea_detail.html",
        {
            "tea": tea,
            "related": related,
            "is_favourite": is_favourite,
            "page_title": tea.name,
            "meta_description": (tea.description or "")[:160],
        },
    )


def brew(request):
    return render(
        request,
        "core/brew.html",
        {
            "teas": list(Tea.objects.all()),
            "page_title": "Brew guide",
            "meta_description": "Precise temperatures, leaf weights, and steep times for every tea.",
        },
    )


def journal(request):
    return render(
        request,
        "core/journal.html",
        {
            "articles": JOURNAL,
            "page_title": "Journal",
            "meta_description": "Articles on brewing parameters, water temperature, caffeine, and terroir.",
        },
    )


def journal_article(request, slug):
    article = next((item for item in JOURNAL if item["slug"] == slug), None)
    if article is None:
        raise Http404("No such article")
    others = [item for item in JOURNAL if item["slug"] != slug]
    return render(
        request,
        "core/journal_article.html",
        {
            "article": article,
            "others": others,
            "page_title": article["title"],
            "meta_description": article["standfirst"][:160],
        },
    )


def faq(request):
    try:
        faqs = list(FAQ.objects.filter(is_active=True).order_by("order"))
    except DatabaseError:
        faqs = []
    return render(
        request,
        "core/faq.html",
        {
            "faqs": faqs,
            "categories": [key for key, _ in FAQ.CATEGORY_CHOICES],
            "page_title": "Questions and answers",
            "meta_description": "Frequently asked questions regarding shipping, returns, brewing, and storage.",
        },
    )


def error_codes(request):
    rows = all_codes()
    return render(
        request,
        "core/error_codes.html",
        {
            "codes": rows,
            "page_title": "Error codes",
            "meta_description": "Explanations and fix steps for every status code shown by this application.",
        },
    )


@csrf_protect
def support(request):
    form_data = {"name": "", "email": "", "subject": "", "message": "", "question": ""}
    errors: dict[str, str] = {}

    if request.method == "POST":
        limited = rate_limited(request, "support-form", 10)
        if limited is not None:
            return render(
                request,
                "core/support.html",
                {
                    "form_data": form_data,
                    "errors": {"form": "Too many attempts. Please wait a minute."},
                    "page_title": "Support",
                },
                status=429,
            )

        form_data["name"] = (request.POST.get("name") or "").strip()
        form_data["email"] = (request.POST.get("email") or "").strip()
        form_data["subject"] = (request.POST.get("subject") or "").strip()
        msg = (request.POST.get("message") or request.POST.get("question") or "").strip()
        form_data["message"] = msg
        form_data["question"] = msg

        if form_data["email"]:
            try:
                validate_email(form_data["email"])
            except ValidationError:
                errors["email"] = "That does not look like an email address."
        else:
            errors["email"] = "We need an email address to reply to."

        if len(msg) < 15:
            errors["question"] = "Please give us a little more detail, at least 15 characters."

        if not errors:
            ticket = Ticket.objects.create(
                name=form_data["name"],
                email=form_data["email"],
                subject=form_data["subject"] or msg[:40],
                message=msg,
                source="form",
                user=request.user if request.user.is_authenticated else None,
            )
            mongo.log_user_event(
                user_id=request.user.pk if request.user.is_authenticated else None,
                event="ticket_created",
                ip=client_ip(request),
                extra={"ticket_id": ticket.ticket_id, "source": "form"},
            )
            return render(
                request,
                "core/support_done.html",
                {"ticket": ticket, "page_title": "Ticket opened"},
            )

    return render(
        request,
        "core/support.html",
        {
            "form_data": form_data,
            "errors": errors,
            "page_title": "Support",
            "meta_description": "Open a support ticket with our customer service team.",
        },
        status=400 if errors else 200,
    )


def brew_plan(request, token):
    plan = get_object_or_404(BrewPlan, token=token)
    return render(
        request,
        "core/brew_plan.html",
        {
            "plan": plan,
            "teas": list(plan.teas.all()),
            "page_title": "A saved recommendation",
        },
    )


# ==========================================================================
# 3. Error Pages and Handlers
# ==========================================================================


def _error_context(code: int) -> dict:
    fallback = static_fallback(code)
    row = None
    try:
        row = ErrorCode.objects.filter(code=str(code)).first()
    except DatabaseError:
        row = None

    if row is not None:
        return {
            "code": row.code,
            "title": row.title,
            "meaning": getattr(row, "meaning", getattr(row, "description", "")),
            "fix": getattr(row, "fix", getattr(row, "fix_steps", "")),
            "from_database": True,
        }
    return {**fallback, "fix": "", "from_database": False}


def handler404(request, exception=None):
    if wants_json(request):
        return json_error("No such endpoint.", 404, 404)
    return render(request, "404.html", _error_context(404), status=404)


def handler500(request):
    if wants_json(request):
        return json_error("Something broke on our side.", 500, 500)
    html = render_to_string("500.html", static_fallback(500))
    return HttpResponse(html, status=500)


def handler400(request, exception=None):
    if wants_json(request):
        return json_error("The site could not read that request.", 400, 400)
    return render(request, "error.html", _error_context(400), status=400)


def handler403(request, exception=None):
    if wants_json(request):
        return json_error("Not yours to see.", 403, 403)
    return render(request, "error.html", _error_context(403), status=403)


def csrf_failure(request, reason="", template_name="error.html"):
    log.warning("CSRF check failed on %s: %s", request.path, reason)
    context = _error_context(403)
    context["note"] = (
        "The security token on that form had expired. Reload the page and send it "
        "again, and nothing will be lost."
    )
    return render(request, "error.html", context, status=403)


def error_page(request, code):
    try:
        number = int(code)
    except (TypeError, ValueError):
        raise Http404("Not an error code")
    if number not in SERVABLE_CODES:
        raise Http404("Not a served error code")

    if number == 500:
        html = render_to_string("500.html", static_fallback(500))
        return HttpResponse(html, status=500)
    return render(request, "error.html", _error_context(number), status=number)


def service_unavailable(request):
    if wants_json(request):
        return json_error(
            "A part of the site is not answering. Please try again shortly.", 503, 503
        )
    html = render_to_string("500.html", {**static_fallback(503), "is_503": True})
    return HttpResponse(html, status=503)


# ==========================================================================
# 4. Service worker, offline, and manifest
# ==========================================================================


def offline(request):
    return render(request, "offline.html", {"page_title": "You are offline"})


@never_cache
def service_worker(request):
    body = render_to_string(
        "core/sw.js",
        {
            "app_version": settings.APP_VERSION,
            "static_url": settings.STATIC_URL,
        },
    )
    response = HttpResponse(body, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def manifest(request):
    data = {
        "name": "Maison Tisane",
        "short_name": "MaisonTisane",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#FAF7F2",
        "theme_color": "#2C3E2D",
        "icons": [
            {
                "src": "/static/core/img/favicon.svg",
                "sizes": "any",
                "type": "image/svg+xml"
            }
        ]
    }
    return JsonResponse(data, content_type="application/manifest+json")


# ==========================================================================
# 5. REST API (/api/...)
# ==========================================================================


@ensure_csrf_cookie
def api_csrf(request):
    """GET /api/csrf/ sets the csrftoken cookie and returns the token in JSON."""
    if request.method != "GET":
        return method_not_allowed(["GET"])
    token = get_token(request)
    return JsonResponse({"csrfToken": token, "ok": True})


def api_faqs(request):
    if request.method != "GET":
        return method_not_allowed(["GET"])
    try:
        qs = FAQ.objects.all().filter(is_active=True) if hasattr(FAQ, "is_active") else FAQ.objects.all()
        rows = [row.to_dict() for row in qs.order_by("order")]
        return JsonResponse({"count": len(rows), "faqs": rows})
    except DatabaseError:
        return json_error("Database unavailable.", 503, 503)


def api_error_codes(request):
    if request.method != "GET":
        return method_not_allowed(["GET"])
    try:
        rows = [row.to_dict() for row in ErrorCode.objects.all()]
        return JsonResponse({"count": len(rows), "error_codes": rows})
    except DatabaseError:
        return json_error("Database unavailable.", 503, 503)


def api_error_code_detail(request, code):
    if request.method != "GET":
        return method_not_allowed(["GET"])
    try:
        row = ErrorCode.objects.filter(code=str(code).upper()).first()
        if row is None:
            row = ErrorCode.objects.filter(code=str(code)).first()
        if row is None:
            return json_error("Error code not found.", 404, 404)
        return JsonResponse(row.to_dict())
    except DatabaseError:
        return json_error("Database unavailable.", 503, 503)


def api_teas(request):
    if request.method != "GET":
        return method_not_allowed(["GET"])

    try:
        queryset = Tea.objects.filter(is_available=True) if hasattr(Tea, "is_available") else Tea.objects.filter(in_stock=True)

        category = request.GET.get("category")
        if category:
            if category not in {key for key, _ in Tea.CATEGORY_CHOICES}:
                return json_error(f"Unknown category '{category}'.", 400, 400)
            queryset = queryset.filter(category=category)

        caffeine = request.GET.get("caffeine")
        if caffeine:
            if caffeine not in {key for key, _ in Tea.CAFFEINE_CHOICES}:
                return json_error(f"Unknown caffeine level '{caffeine}'.", 400, 400)
            queryset = queryset.filter(caffeine=caffeine)

        weather = request.GET.get("weather")
        if weather and hasattr(Tea, "best_for_weather"):
            valid_weather = {key for key, _ in Tea.WEATHER_CHOICES}
            if weather not in valid_weather:
                return json_error(f"Unknown weather filter '{weather}'.", 400, 400)
            queryset = queryset.filter(best_for_weather=weather)

        mood = request.GET.get("mood")
        if mood:
            if mood not in Tea.MOOD_CHOICES:
                return json_error(f"Unknown mood '{mood}'.", 400, 400)
            queryset = queryset.filter(moods__icontains=mood)

        slugs = request.GET.get("slugs")
        if slugs:
            wanted = [part.strip() for part in slugs.split(",") if part.strip()]
            queryset = queryset.filter(slug__in=wanted)

        term = (request.GET.get("q") or "").strip()
        if term:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(name__icontains=term)
                | Q(flavour_notes__icontains=term)
                | Q(tasting_notes__icontains=term)
                | Q(origin__icontains=term)
                | Q(description__icontains=term)
            )

        rows = [tea.to_dict() for tea in queryset]
        return JsonResponse({"count": len(rows), "teas": rows})
    except DatabaseError:
        return json_error("Database unavailable.", 503, 503)


def api_tea_detail(request, slug):
    if request.method != "GET":
        return method_not_allowed(["GET"])
    try:
        tea = Tea.objects.filter(slug=slug).first()
        if tea is None:
            return json_error("No tea with that slug.", 404, 404)
        return JsonResponse(tea.to_dict())
    except DatabaseError:
        return json_error("Database unavailable.", 503, 503)


def api_weather(request):
    if request.method != "GET":
        return method_not_allowed(["GET"])
    city = (request.GET.get("city") or weather_service.DEFAULT_CITY).strip().title()
    if city not in weather_service.CITIES:
        return json_error(
            f"Unknown city '{city}'. Choose one of: "
            + ", ".join(weather_service.CITIES),
            400,
            400,
        )
    return JsonResponse(weather_service.for_city(city))


def api_weather_tea(request):
    """
    GET /api/weather-tea/?lat=&lon=
    Calls Open-Meteo, maps to weather type, returns 3 teas.
    """
    if request.method != "GET":
        return method_not_allowed(["GET"])

    lat_str = request.GET.get("lat")
    lon_str = request.GET.get("lon")

    if not lat_str or not lon_str:
        return json_error("Provide 'lat' and 'lon' query parameters.", 400, 400)

    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return json_error("Latitude and longitude must be numbers.", 400, 400)

    result = weather_service.get_weather_tea(lat, lon)
    return JsonResponse(result)


@csrf_exempt
def api_tickets(request):
    """
    POST is public (support form/API). Returns 201.
    GET lists tickets and requires bearer token (401).
    """
    if request.method == "POST":
        limited = rate_limited(request, "tickets", 10)
        if limited is not None:
            return limited

        try:
            payload = read_json(request)
        except ValueError as exc:
            return json_error(str(exc), 400, 400)

        name = (payload.get("name") or "").strip()[:120]
        email = (payload.get("email") or "").strip()[:254]
        subject = (payload.get("subject") or "").strip()[:200]
        message = (payload.get("message") or payload.get("question") or "").strip()[:2000]

        if len(message) < 15:
            return json_error(
                "Please give at least 15 characters of detail in 'message' or 'question'.",
                400,
                400,
            )

        if email:
            try:
                validate_email(email)
            except ValidationError:
                return json_error("That is not a valid email address.", 400, 400)

        user_obj = request.user if request.user.is_authenticated else None
        ticket = Ticket.objects.create(
            name=name,
            email=email,
            subject=subject or message[:40],
            message=message,
            source="api",
            user=user_obj,
        )

        # Log to Mongo without email
        mongo.log_user_event(
            user_id=user_obj.pk if user_obj else None,
            event="ticket_created",
            ip=client_ip(request),
            extra={"ticket_id": ticket.ticket_id, "status": ticket.status},
        )

        return JsonResponse({
            "ticket_id": ticket.ticket_id,
            "status": ticket.status,
            "id": ticket.pk,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }, status=201)

    if request.method == "GET":
        denied = staff_token_error(request)
        if denied is not None:
            return denied

        status = request.GET.get("status")
        queryset = Ticket.objects.all()
        if status:
            if status not in {key for key, _ in Ticket.STATUS_CHOICES}:
                return json_error(f"Unknown status '{status}'.", 400, 400)
            queryset = queryset.filter(status=status)

        # Pagination
        try:
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            page = 1
        page_size = 20
        start = (page - 1) * page_size
        rows = [row.to_dict() for row in queryset[start:start + page_size]]

        return JsonResponse({
            "count": queryset.count(),
            "page": page,
            "tickets": rows,
        })

    return method_not_allowed(["GET", "POST"])


@csrf_exempt
def api_ticket_detail(request, ticket_id):
    """Read, update status of, or delete one ticket. Staff token required (401)."""
    if request.method not in {"GET", "PATCH", "DELETE"}:
        return method_not_allowed(["GET", "PATCH", "DELETE"])

    denied = staff_token_error(request)
    if denied is not None:
        return denied

    # Support lookup by MT- ticket_id or integer ID
    ticket = None
    if str(ticket_id).isdigit():
        ticket = Ticket.objects.filter(pk=int(ticket_id)).first()
    if ticket is None:
        ticket = Ticket.objects.filter(ticket_id=str(ticket_id)).first()
    if ticket is None:
        return json_error("No ticket with that id.", 404, 404)

    if request.method == "GET":
        return JsonResponse(ticket.to_dict())

    if request.method == "PATCH":
        try:
            payload = read_json(request)
        except ValueError as exc:
            return json_error(str(exc), 400, 400)

        status = (payload.get("status") or "").strip()
        valid = {key for key, _ in Ticket.STATUS_CHOICES}
        if not status:
            return json_error("Send a 'status' field.", 400, 400)
        if status not in valid:
            return json_error(
                f"Invalid status '{status}'. Use one of: " + ", ".join(sorted(valid)),
                400,
                400,
            )
        ticket.status = status
        ticket.save(update_fields=["status", "updated_at"])
        return JsonResponse(ticket.to_dict())

    ticket.delete()
    return HttpResponse(status=204)


@csrf_protect
def api_subscribe(request):
    """
    POST /api/subscribe/
    Body: {email}
    Returns 200 with already_subscribed: true on duplicate, 201 on new.
    """
    if request.method != "POST":
        return method_not_allowed(["POST"])

    limited = rate_limited(request, "subscribe", 10)
    if limited is not None:
        return limited

    try:
        payload = read_json(request)
    except ValueError as exc:
        return json_error(str(exc), 400, 400)

    raw_email = (payload.get("email") or "").strip()
    first_name = (payload.get("first_name") or "").strip()

    if not raw_email:
        return json_error("Please give an email address.", 400, 400)

    try:
        validate_email(raw_email)
    except ValidationError:
        return json_error("That is not a valid email address.", 400, 400)

    email = raw_email.lower()

    existing = Subscriber.objects.filter(email=email).first()
    if existing is not None:
        return JsonResponse({
            "ok": True,
            "already_subscribed": True,
            "email": email,
        }, status=200)

    subscriber = Subscriber.objects.create(
        email=email,
        first_name=first_name or email.split("@")[0],
    )

    # Log to MongoDB without raw email
    user_id = request.user.pk if request.user.is_authenticated else None
    mongo.log_user_event(
        user_id=user_id,
        event="subscribe",
        ip=client_ip(request),
    )

    return JsonResponse({
        "ok": True,
        "already_subscribed": False,
        "subscriber": subscriber.to_dict(),
    }, status=201)


@csrf_exempt
def api_chat(request):
    """
    POST /api/chat/
    Body: {message, session_id, page}
    """
    if request.method != "POST":
        return method_not_allowed(["POST"])

    try:
        payload = read_json(request)
    except ValueError as exc:
        return json_error(str(exc), 400, 400)

    message = payload.get("message")
    session_id = str(payload.get("session_id") or "")[:64]
    page = str(payload.get("page") or "/")[:200]
    email = (payload.get("email") or "").strip()

    # Rate limiting
    limited = rate_limited(request, "chat", 20, session_id=session_id)
    if limited is not None:
        return limited

    if email:
        try:
            validate_email(email)
        except ValidationError:
            return json_error("That is not a valid email address.", 400, 400)

    context = {
        "page": page,
        "shortlist": [str(s)[:140] for s in (payload.get("shortlist") or [])[:20]],
        "city": (payload.get("city") or "").strip()[:60] or None,
    }

    started = time.monotonic()
    try:
        result = chat_service.answer(
            message=message,
            email=email,
            context=context,
            user=request.user,
        )
    except chat_service.InvalidInput as exc:
        return json_error(str(exc), 400, 400)
    except DatabaseError as exc:
        log.error("Chat failed, database error: %s", exc)
        return json_error("I cannot reach my records just now. Please try again shortly.", 503, 503)

    message_id = uuid.uuid4().hex[:16]
    latency_ms = result.get("latency_ms") or int((time.monotonic() - started) * 1000)

    # Log to MongoDB (best effort)
    user_id = request.user.pk if request.user.is_authenticated else None
    mongo.log_chat(
        message_id=message_id,
        session_id=session_id,
        page=page,
        user_message=str(message)[:2000],
        reply=result.get("reply", ""),
        source=result.get("source", "unknown"),
        ticket_id=result.get("ticket_id"),
        latency_ms=latency_ms,
        ip=client_ip(request),
        user_id=user_id,
    )

    body = {
        "message_id": message_id,
        "reply": result.get("reply", ""),
        "source": result.get("source", "unknown"),
        "ticket_id": result.get("ticket_id"),
        "latency_ms": latency_ms,
    }
    for opt in ("action", "teas", "code", "weather"):
        if opt in result and result[opt] is not None:
            body[opt] = result[opt]

    return JsonResponse(body)


@csrf_exempt
def api_feedback(request):
    """
    POST /api/feedback/
    Body: {message_id, session_id, value, page}
    """
    if request.method != "POST":
        return method_not_allowed(["POST"])

    limited = rate_limited(request, "feedback", 30)
    if limited is not None:
        return limited

    try:
        payload = read_json(request)
    except ValueError as exc:
        return json_error(str(exc), 400, 400)

    value = (payload.get("value") or "").strip().lower()
    if value not in {"up", "down"}:
        return json_error("Send 'value' as 'up' or 'down'.", 400, 400)

    message_id = str(payload.get("message_id") or "").strip()[:64]
    if not message_id:
        return json_error("Send the 'message_id' of the reply.", 400, 400)

    session_id = str(payload.get("session_id") or "")[:64]
    page = str(payload.get("page") or "/")[:200]
    user_id = request.user.pk if request.user.is_authenticated else None

    stored = mongo.save_feedback(
        message_id=message_id,
        session_id=session_id,
        value=value,
        page=page,
        user_id=user_id,
    )

    mongo.log_user_event(
        user_id=user_id,
        event="feedback",
        ip=client_ip(request),
        session_id=session_id,
        extra={"message_id": message_id, "value": value},
    )

    return JsonResponse({"ok": True, "stored": stored})


@csrf_exempt
def api_brew_plans(request):
    if request.method != "POST":
        return method_not_allowed(["POST"])

    limited = rate_limited(request, "brew-plans", 10)
    if limited is not None:
        return limited

    try:
        payload = read_json(request)
    except ValueError as exc:
        return json_error(str(exc), 400, 400)

    prompt = (payload.get("prompt") or "").strip()[:500]
    slugs = [str(s)[:140] for s in (payload.get("teas") or [])[:6]]
    if not slugs:
        return json_error("Send at least one tea slug in 'teas'.", 400, 400)

    found = list(Tea.objects.filter(slug__in=slugs))
    if not found:
        return json_error("None of those tea slugs exist.", 400, 400)

    plan = BrewPlan.objects.create(prompt=prompt or "A saved recommendation")
    plan.teas.set(found)
    return JsonResponse(plan.to_dict(), status=201)


# ==========================================================================
# 6. Accounts & Health
# ==========================================================================


def _check_database() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}
    return {"ok": True, "detail": "reachable"}


@never_cache
def health(request):
    database = _check_database()
    mongo_ok, mongo_detail = mongo.ping()
    mongo_check = {
        "ok": mongo_ok,
        "configured": mongo.is_configured(),
        "detail": mongo_detail,
    }

    from core.services import gemini as gemini_service
    model_check = {
        "ok": gemini_service.model_is_available(),
        "configured": gemini_service.model_is_available(),
        "model": getattr(settings, "GEMINI_MODEL", ""),
        "detail": (
            "key present"
            if gemini_service.model_is_available()
            else "no key set, assistant runs on saved answers"
        ),
    }

    weather_status = weather_service.last_status()
    weather_check = {
        "ok": weather_status["source"] != "fallback" if weather_status["checked"] else True,
        "detail": (
            f"last lookup for {weather_status['city']} used the {weather_status['source']}"
            if weather_status["checked"]
            else "no lookup yet this process"
        ),
    }

    optional_down = [
        name
        for name, check in (
            ("mongodb", mongo_check),
            ("assistant model", model_check),
            ("weather", weather_check),
        )
        if not check["ok"]
    ]

    if not database["ok"]:
        status_word = "down"
        http_status = 503
    elif optional_down:
        status_word = "degraded"
        http_status = 200
    else:
        status_word = "ok"
        http_status = 200

    counts = {}
    if database["ok"]:
        try:
            counts = {
                "teas": Tea.objects.count(),
                "faqs": FAQ.objects.count(),
                "error_codes": ErrorCode.objects.count(),
                "tickets": Ticket.objects.count(),
            }
        except DatabaseError:
            counts = {}

    payload = {
        "status": status_word,
        "version": getattr(settings, "APP_VERSION", "1.0.0"),
        "checks": {
            "database": database,
            "mongodb": mongo_check,
            "assistant_model": model_check,
            "weather_api": weather_check,
        },
        "counts": counts,
        "degraded": optional_down,
    }

    if request.GET.get("format") == "json":
        return JsonResponse(payload, status=http_status)

    return render(
        request,
        "core/health.html",
        {**payload, "page_title": "Status"},
        status=http_status,
    )


@csrf_protect
def register(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST":
        limited = rate_limited(request, "register", 10)
        if limited is not None:
            return render(
                request,
                "core/register.html",
                {"form": form, "page_title": "Create an account", "rate_limited": True},
                status=429,
            )
        if form.is_valid():
            user = form.save()
            login(request, user)
            mongo.upsert_user(user)
            mongo.log_user_event(
                user_id=user.pk,
                event="signup",
                ip=client_ip(request),
                extra={"username": user.username},
            )
            messages.success(request, "Your account is ready.")
            return redirect("account")
    return render(
        request,
        "core/register.html",
        {"form": form, "page_title": "Create an account"},
    )


@csrf_protect
def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)
    next_url = request.GET.get("next") or request.POST.get("next") or ""

    if request.method == "POST":
        limited = rate_limited(request, "login", 10)
        if limited is not None:
            return render(
                request,
                "core/login.html",
                {"form": form, "next": next_url, "page_title": "Sign in", "rate_limited": True},
                status=429,
            )
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            mongo.upsert_user(user)
            mongo.log_user_event(
                user_id=user.pk,
                event="login",
                ip=client_ip(request),
            )
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect("account")

    return render(
        request,
        "core/login.html",
        {"form": form, "next": next_url, "page_title": "Sign in"},
    )


@login_required
def account(request):
    favourites = list(
        Favourite.objects.filter(user=request.user).select_related("tea")
    )
    return render(
        request,
        "core/account.html",
        {
            "favourites": favourites,
            "page_title": "Your account",
        },
    )


@login_required
@csrf_protect
def toggle_favourite(request, slug):
    if request.method != "POST":
        return method_not_allowed(["POST"])
    tea = get_object_or_404(Tea, slug=slug)
    existing = Favourite.objects.filter(user=request.user, tea=tea).first()
    if existing is not None:
        existing.delete()
        saved = False
    else:
        Favourite.objects.create(user=request.user, tea=tea)
        saved = True

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"saved": saved, "slug": slug})
    return redirect(tea.get_absolute_url())
