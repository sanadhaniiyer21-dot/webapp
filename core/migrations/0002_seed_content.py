"""
Seed the catalogue, the FAQ and the error code table.

The rows themselves live in core/content.py so the shop's words can be
proofread in one readable file rather than inside a migration. This migration
is the step that puts them into SQL.

It uses update_or_create keyed on the natural key of each table (slug, code,
question), so running it against a database that already has the rows corrects
them instead of duplicating them.
"""

from django.db import migrations

from core.content import ERROR_CODES, FAQS, TEAS


def seed(apps, schema_editor):
    Tea = apps.get_model("core", "Tea")
    FAQ = apps.get_model("core", "FAQ")
    ErrorCode = apps.get_model("core", "ErrorCode")

    # Clean up any old teas not in current list of 24
    current_slugs = [row["slug"] for row in TEAS]
    Tea.objects.exclude(slug__in=current_slugs).delete()

    for row in TEAS:
        fields = {key: value for key, value in row.items() if key != "slug"}
        Tea.objects.update_or_create(slug=row["slug"], defaults=fields)

    # Clean up any old FAQs not in current list
    current_questions = [row["question"] for row in FAQS]
    FAQ.objects.exclude(question__in=current_questions).delete()

    for row in FAQS:
        fields = {key: value for key, value in row.items() if key != "question"}
        FAQ.objects.update_or_create(question=row["question"], defaults=fields)

    # Clean up any old ErrorCodes not in current list of 12
    current_codes = [row["code"] for row in ERROR_CODES]
    ErrorCode.objects.exclude(code__in=current_codes).delete()

    for row in ERROR_CODES:
        fields = {key: value for key, value in row.items() if key != "code"}
        ErrorCode.objects.update_or_create(code=row["code"], defaults=fields)


def unseed(apps, schema_editor):
    """Remove only the rows this migration added."""
    Tea = apps.get_model("core", "Tea")
    FAQ = apps.get_model("core", "FAQ")
    ErrorCode = apps.get_model("core", "ErrorCode")

    Tea.objects.filter(slug__in=[row["slug"] for row in TEAS]).delete()
    FAQ.objects.filter(question__in=[row["question"] for row in FAQS]).delete()
    ErrorCode.objects.filter(code__in=[row["code"] for row in ERROR_CODES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
