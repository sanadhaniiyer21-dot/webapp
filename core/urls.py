"""
Every address in the site, grouped by what it is for.
"""

from django.contrib.auth import views as auth_views
from django.urls import path

from core import views

urlpatterns = [
    # ---- Pages ---------------------------------------------------------
    path("", views.home, name="home"),
    path("teas/", views.teas, name="teas"),
    path("teas/<slug:slug>/", views.tea_detail, name="tea_detail"),
    path("brew/", views.brew, name="brew"),
    path("journal/", views.journal, name="journal"),
    path("journal/<slug:slug>/", views.journal_article, name="journal_article"),
    path("faq/", views.faq, name="faq"),
    path("error-codes/", views.error_codes, name="error_codes"),
    path("support/", views.support, name="support"),
    path("plan/<str:token>/", views.brew_plan, name="brew_plan"),

    # ---- Status, offline, service worker, manifest --------------------
    path("health/", views.health, name="health"),
    path("offline/", views.offline, name="offline"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("manifest.webmanifest", views.manifest, name="manifest"),

    # ---- Error pages, openable directly -------------------------------
    path("error/<int:code>/", views.error_page, name="error_page"),

    # ---- API -----------------------------------------------------------
    path("api/csrf/", views.api_csrf, name="api_csrf"),
    path("api/faqs/", views.api_faqs, name="api_faqs"),
    path("api/error-codes/", views.api_error_codes, name="api_error_codes"),
    path("api/error-codes/<str:code>/", views.api_error_code_detail, name="api_error_code_detail"),
    path("api/teas/", views.api_teas, name="api_teas"),
    path("api/teas/<slug:slug>/", views.api_tea_detail, name="api_tea_detail"),
    path("api/weather/", views.api_weather, name="api_weather"),
    path("api/weather-tea/", views.api_weather_tea, name="api_weather_tea"),
    path("api/tickets/", views.api_tickets, name="api_tickets"),
    path("api/tickets/<str:ticket_id>/", views.api_ticket_detail, name="api_ticket_detail"),
    path("api/subscribe/", views.api_subscribe, name="api_subscribe"),
    path("api/chat/", views.api_chat, name="api_chat"),
    path("api/feedback/", views.api_feedback, name="api_feedback"),
    path("api/brew-plans/", views.api_brew_plans, name="api_brew_plans"),

    # ---- Accounts ------------------------------------------------------
    path("accounts/", views.account, name="account"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.login_view, name="login"),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(next_page="/"),
        name="logout",
    ),
    path("accounts/favourite/<slug:slug>/", views.toggle_favourite, name="toggle_favourite"),
]
