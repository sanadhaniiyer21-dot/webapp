"""
Project URLs.

The four handler assignments are what make the custom error pages actually
appear. Without them Django serves its own bare pages, and checklist item 5
fails even though the templates exist.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

handler400 = "core.views.handler400"
handler403 = "core.views.handler403"
handler404 = "core.views.handler404"
handler500 = "core.views.handler500"
