"""
SQL models for Maison Tisane.

Everything the assistant says about a tea, an FAQ or an error code is read from
these tables, so the language model can never invent a price or a brewing
temperature. Chat transcripts, feedback, users, and events live in MongoDB.
"""

import datetime
import secrets
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse


def split_list(raw: str) -> list[str]:
    """Turn a stored comma separated field into a clean list."""
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


@lru_cache(maxsize=512)
def image_for_slug(slug: str) -> str:
    """Prefer a real photograph over the generated illustration."""
    folder = Path(settings.BASE_DIR) / "core" / "static" / "core" / "img" / "teas"
    for extension in ("jpg", "jpeg", "webp", "png"):
        if (folder / f"{slug}.{extension}").exists():
            return f"core/img/teas/{slug}.{extension}"
    return f"core/img/teas/{slug}.svg"


def generate_ticket_id() -> str:
    """Generate unique ticket ID in format MT-YYYYMMDD-XXXX."""
    date_str = datetime.date.today().strftime("%Y%m%d")
    random_hex = secrets.token_hex(2).upper()
    return f"MT-{date_str}-{random_hex}"


class Tea(models.Model):
    """One loose-leaf tea or tisane in the catalogue."""

    CATEGORY_CHOICES = [
        ("green", "Green"),
        ("black", "Black"),
        ("oolong", "Oolong"),
        ("white", "White"),
        ("dark", "Dark"),
        ("matcha", "Matcha"),
        ("tisane", "Tisane"),
        ("blend", "Blend"),
        ("herbal", "Herbal"),
        ("rooibos", "Rooibos"),
        ("chai", "Chai"),
    ]
    CAFFEINE_CHOICES = [
        ("none", "None"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]
    WEATHER_CHOICES = [
        ("hot", "Hot"),
        ("cold", "Cold"),
        ("rainy", "Rainy"),
        ("mild", "Mild"),
    ]
    MOOD_CHOICES = [
        "calm", "focus", "morning", "afternoon",
        "evening", "comfort", "iced", "digestive",
    ]

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    origin = models.CharField(max_length=160, blank=True, default="", help_text="Region and country.")
    
    # Caffeine fields
    caffeine = models.CharField(max_length=8, choices=CAFFEINE_CHOICES, default="medium")
    caffeine_level = models.CharField(max_length=8, choices=CAFFEINE_CHOICES, default="medium")

    # Tasting / flavour notes
    flavour_notes = models.CharField(max_length=240, blank=True, default="", help_text="Comma separated tasting notes.")
    tasting_notes = models.CharField(max_length=240, blank=True, default="", help_text="Comma separated tasting notes.")
    moods = models.CharField(max_length=160, blank=True, default="", help_text="Comma separated moods.")

    # Brewing parameters
    brew_temp_c = models.PositiveSmallIntegerField(default=85, help_text="Water temperature in Celsius.")
    steep_seconds = models.PositiveSmallIntegerField(default=180, help_text="First steep, in seconds.")
    brew_time_min = models.DecimalField(max_digits=4, decimal_places=1, default=3.0, help_text="Steep time in minutes.")
    grams_per_200ml = models.DecimalField(max_digits=4, decimal_places=1, default=3.0)
    resteeps = models.PositiveSmallIntegerField(default=0, help_text="Further steeps after the first.")

    # Pricing & availability
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)
    price_inr_50g = models.PositiveIntegerField(default=0, help_text="Rupees per 50 g.")
    in_stock = models.BooleanField(default=True)
    is_available = models.BooleanField(default=True)

    # Weather matching
    best_for_weather = models.CharField(max_length=16, choices=WEATHER_CHOICES, default="mild")

    description = models.TextField(blank=True, default="")
    pairing = models.CharField(max_length=200, blank=True, default="", help_text="What to eat with it.")
    image = models.CharField(max_length=200, blank=True, default="", help_text="Path to static image.")
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "tea"
        verbose_name_plural = "teas"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        # Sync duplicate fields
        if not self.tasting_notes and self.flavour_notes:
            self.tasting_notes = self.flavour_notes
        elif not self.flavour_notes and self.tasting_notes:
            self.flavour_notes = self.tasting_notes

        if not self.caffeine_level and self.caffeine:
            self.caffeine_level = self.caffeine
        elif not self.caffeine and self.caffeine_level:
            self.caffeine = self.caffeine_level

        if not self.price and self.price_inr_50g:
            self.price = self.price_inr_50g
        elif not self.price_inr_50g and self.price:
            self.price_inr_50g = int(self.price)

        if not self.brew_time_min and self.steep_seconds:
            self.brew_time_min = round(self.steep_seconds / 60, 1)
        elif not self.steep_seconds and self.brew_time_min:
            self.steep_seconds = int(float(self.brew_time_min) * 60)

        self.in_stock = self.is_available
        if not self.image:
            self.image = image_for_slug(self.slug)

        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("tea_detail", args=[self.slug])

    @property
    def note_list(self) -> list[str]:
        return split_list(self.flavour_notes or self.tasting_notes)

    @property
    def mood_list(self) -> list[str]:
        return split_list(self.moods)

    @property
    def steep_label(self) -> str:
        """'3 min' or '45 sec', whichever reads better."""
        secs = self.steep_seconds or int(float(self.brew_time_min or 3) * 60)
        if secs >= 60 and secs % 60 == 0:
            minutes = secs // 60
            return f"{minutes} min"
        if secs >= 60:
            return f"{secs // 60} min {secs % 60} sec"
        return f"{secs} sec"

    @property
    def image_name(self) -> str:
        return self.image or image_for_slug(self.slug)

    def brewing_sentence(self) -> str:
        """The one line the assistant quotes for brewing."""
        grams = f"{self.grams_per_200ml:g}"
        line = (
            f"{grams} g per 200 ml, water at {self.brew_temp_c} C, "
            f"steep {self.steep_label}"
        )
        if self.resteeps == 1:
            line += ", then one more steep"
        elif self.resteeps > 1:
            line += f", then up to {self.resteeps} more steeps"
        return line + "."

    @property
    def caffeine_phrase(self) -> str:
        caff = self.caffeine or self.caffeine_level
        if caff == "none":
            return "no caffeine"
        return f"{self.get_caffeine_display().lower()} caffeine"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "origin": self.origin,
            "caffeine": self.caffeine,
            "caffeine_level": self.caffeine_level,
            "flavour_notes": self.note_list,
            "tasting_notes": self.tasting_notes or self.flavour_notes,
            "moods": self.mood_list,
            "brew_temp_c": self.brew_temp_c,
            "steep_seconds": self.steep_seconds,
            "brew_time_min": float(self.brew_time_min),
            "steep_label": self.steep_label,
            "grams_per_200ml": float(self.grams_per_200ml),
            "resteeps": self.resteeps,
            "price": float(self.price),
            "price_inr_50g": self.price_inr_50g,
            "in_stock": self.in_stock,
            "is_available": self.is_available,
            "best_for_weather": self.best_for_weather,
            "image": self.image_name,
            "description": self.description,
            "pairing": self.pairing,
            "url": self.get_absolute_url(),
        }


class FAQ(models.Model):
    """A shop question with its settled answer."""

    CATEGORY_CHOICES = [
        ("Ordering", "Ordering"),
        ("Shipping", "Shipping"),
        ("Brewing", "Brewing"),
        ("Storage", "Storage"),
        ("Account", "Account"),
        ("Assistant", "Assistant"),
        ("Payment", "Payment"),
        ("General", "General"),
    ]

    question = models.CharField(max_length=255)
    answer = models.TextField()
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    keywords = models.CharField(max_length=255, blank=True, default="", help_text="Comma-separated keywords.")
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self) -> str:
        return self.question

    def to_dict(self) -> dict:
        return {
            "id": self.pk,
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "keywords": self.keywords,
            "is_active": self.is_active,
            "order": self.order,
        }


class ErrorCode(models.Model):
    """What a code means and what to do about it, in plain words."""

    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    code = models.CharField(max_length=16, unique=True)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="", help_text="What happened.")
    meaning = models.TextField(blank=True, default="", help_text="What happened.")
    fix_steps = models.TextField(blank=True, default="", help_text="What the visitor should do next.")
    fix = models.TextField(blank=True, default="", help_text="What the visitor should do next.")
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default="medium")

    class Meta:
        ordering = ["code"]
        verbose_name = "error code"
        verbose_name_plural = "error codes"

    def __str__(self) -> str:
        return f"{self.code} {self.title}"

    def save(self, *args, **kwargs):
        if not self.description and self.meaning:
            self.description = self.meaning
        elif not self.meaning and self.description:
            self.meaning = self.description

        if not self.fix_steps and self.fix:
            self.fix_steps = self.fix
        elif not self.fix and self.fix_steps:
            self.fix = self.fix_steps

        super().save(*args, **kwargs)

    @property
    def is_site_code(self) -> bool:
        return self.code.startswith("SITE-") or self.code.startswith("MT-")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "description": self.description or self.meaning,
            "meaning": self.meaning or self.description,
            "fix_steps": self.fix_steps or self.fix,
            "fix": self.fix or self.fix_steps,
            "severity": self.severity,
        }

    def as_reply(self) -> str:
        """The assistant's wording for this code."""
        desc = self.description or self.meaning
        steps = self.fix_steps or self.fix
        return f"{self.code}, {self.title}. {desc} What to do: {steps}"


class Ticket(models.Model):
    """A customer service ticket."""

    SOURCE_CHOICES = [
        ("web_form", "Web form"),
        ("form", "Support form"),
        ("chat", "Chat assistant"),
        ("api", "API"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    ticket_id = models.CharField(max_length=32, unique=True, blank=True, db_index=True)
    name = models.CharField(max_length=120, blank=True, default="")
    email = models.EmailField(blank=True, default="", help_text="Blank if the visitor gave none.")
    subject = models.CharField(max_length=200, blank=True, default="")
    message = models.TextField(blank=True, default="")
    question = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="web_form")
    session_id = models.CharField(max_length=64, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        ref = self.ticket_id or f"#{self.pk}"
        return f"Ticket {ref} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            self.ticket_id = generate_ticket_id()
        if not self.message and self.question:
            self.message = self.question
        elif not self.question and self.message:
            self.question = self.message
        super().save(*args, **kwargs)

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "id": self.pk,
            "name": self.name,
            "email": self.email,
            "subject": self.subject,
            "message": self.message or self.question,
            "question": self.question or self.message,
            "source": self.source,
            "status": self.status,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Subscriber(models.Model):
    """A newsletter signup."""

    first_name = models.CharField(max_length=80, blank=True, default="")
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    consented_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ["-consented_at"]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if not self.first_name and self.email:
            self.first_name = self.email.split("@")[0]
        super().save(*args, **kwargs)

    def to_dict(self) -> dict:
        return {
            "id": self.pk,
            "first_name": self.first_name,
            "email": self.email,
            "is_active": self.is_active,
            "consented_at": self.consented_at.isoformat() if self.consented_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Favourite(models.Model):
    """A signed-in visitor's saved tea."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favourites"
    )
    tea = models.ForeignKey(Tea, on_delete=models.CASCADE, related_name="favourited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "tea"], name="unique_user_tea_favourite")
        ]

    def __str__(self) -> str:
        return f"{self.user} likes {self.tea}"


def make_token() -> str:
    return secrets.token_urlsafe(8)


class BrewPlan(models.Model):
    """A saved recommendation shared by token."""

    token = models.CharField(max_length=24, unique=True, default=make_token)
    prompt = models.CharField(max_length=500, help_text="What the visitor asked.")
    teas = models.ManyToManyField(Tea, related_name="brew_plans")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Brew plan {self.token}"

    def get_absolute_url(self) -> str:
        return reverse("brew_plan", args=[self.token])

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "prompt": self.prompt,
            "teas": [tea.slug for tea in self.teas.all()],
            "url": self.get_absolute_url(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
