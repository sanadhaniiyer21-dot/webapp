"""
Template context shared by every page.

Deliberately database-free. The error pages and the offline page use the same
base variables, and they have to render when the database is the thing that
has failed.
"""

from datetime import date

from django.conf import settings

# One list, so the navigation and the footer can never disagree.
NAV = [
    {"label": "Teas", "url_name": "teas", "path": "/teas/"},
    {"label": "Brew guide", "url_name": "brew", "path": "/brew/"},
    {"label": "Journal", "url_name": "journal", "path": "/journal/"},
    {"label": "FAQ", "url_name": "faq", "path": "/faq/"},
]

FOOTER_LINKS = [
    {"label": "Error codes", "path": "/error-codes/"},
    {"label": "Support", "path": "/support/"},
    {"label": "Status", "path": "/health/"},
]


def site(request):
    return {
        "site_name": "Maison Tisane",
        "site_tagline": "Loose-leaf tea, explained plainly.",
        "nav": NAV,
        "footer_links": FOOTER_LINKS,
        "app_version": settings.APP_VERSION,
        "site_url": settings.SITE_URL,
        "current_year": date.today().year,
        "current_path": getattr(request, "path", "/"),
    }
