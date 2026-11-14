"""
Admin screens, so the shop can be run without touching the database by hand.
"""

from django.contrib import admin

from core.models import FAQ, BrewPlan, ErrorCode, Favourite, Subscriber, Tea, Ticket

admin.site.site_header = "Maison Tisane"
admin.site.site_title = "Maison Tisane admin"
admin.site.index_title = "Shop administration"


@admin.register(Tea)
class TeaAdmin(admin.ModelAdmin):
    list_display = (
        "name", "category", "origin", "caffeine",
        "brew_temp_c", "steep_seconds", "price_inr_50g", "best_for_weather", "is_available", "order",
    )
    list_filter = ("category", "caffeine", "best_for_weather", "is_available")
    search_fields = ("name", "origin", "flavour_notes", "tasting_notes", "description")
    prepopulated_fields = {"slug": ("name",)}
    list_editable = ("order",)
    fieldsets = (
        (None, {"fields": ("name", "slug", "category", "origin", "order", "is_available", "best_for_weather")}),
        ("Tasting", {"fields": ("caffeine", "caffeine_level", "flavour_notes", "tasting_notes", "moods", "description", "pairing")}),
        ("Brewing", {"fields": ("brew_temp_c", "steep_seconds", "brew_time_min", "grams_per_200ml", "resteeps")}),
        ("Price & Art", {"fields": ("price", "price_inr_50g", "image")}),
    )


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "category", "is_active", "order")
    list_filter = ("category", "is_active")
    search_fields = ("question", "answer", "keywords")
    list_editable = ("order", "is_active")


@admin.register(ErrorCode)
class ErrorCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "severity", "is_site_code")
    list_filter = ("severity",)
    search_fields = ("code", "title", "description", "meaning", "fix_steps", "fix")

    @admin.display(boolean=True, description="Site specific")
    def is_site_code(self, obj):
        return obj.is_site_code


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_id", "short_subject", "email", "source", "status", "created_at")
    list_filter = ("status", "source", "created_at")
    search_fields = ("ticket_id", "subject", "message", "question", "email", "name")
    list_editable = ("status",)
    readonly_fields = ("created_at", "updated_at", "ticket_id")
    date_hierarchy = "created_at"

    @admin.display(description="Subject / Message")
    def short_subject(self, obj):
        text = obj.subject or obj.message or obj.question or ""
        return text if len(text) <= 70 else text[:70] + "..."


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("email", "first_name")
    readonly_fields = ("created_at", "consented_at")


@admin.register(Favourite)
class FavouriteAdmin(admin.ModelAdmin):
    list_display = ("user", "tea", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "tea__name")
    autocomplete_fields = ("tea",)


@admin.register(BrewPlan)
class BrewPlanAdmin(admin.ModelAdmin):
    list_display = ("token", "prompt", "created_at")
    list_filter = ("created_at",)
    search_fields = ("token", "prompt")
    readonly_fields = ("token", "created_at")
    filter_horizontal = ("teas",)
