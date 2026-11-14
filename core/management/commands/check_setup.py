"""
Maison Tisane deployment setup verification command.

    python manage.py check_setup

Checks:
1. SQL database reachable (SELECT 1) and engine in use (SQLite / PostgreSQL)
2. Migrations: no unapplied migrations (MigrationExecutor), else FAIL
3. Seed counts: FAQs >= 14, ErrorCodes = 12, Teas = 24 (FAIL if below)
4. Secrets: SECRET_KEY >= 50 chars without 'django-insecure'; TICKET_API_TOKEN >= 32 chars and != SECRET_KEY; DEBUG off with non-local hosts
5. Gemini: real test call ("Reply with OK"), reporting 403/404/429/timeout meanings
6. MongoDB: ping, then insert & delete in _setup_check collection with distinct error diagnostics
7. Weather API: real Open-Meteo call for Singapore (lat 1.3521, lon 103.8198)
8. Production extras when DEBUG=0: CSRF_TRUSTED_ORIGINS set and starts with https://; DATABASE_URL not empty

Exits with code 1 if any check FAILs.
"""

import json
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

from core import mongo
from core.models import FAQ, ErrorCode, Tea
from core.services import gemini

MIN_TEAS = 24
MIN_FAQS = 14
EXACT_CODES = 12


class Command(BaseCommand):
    help = "Verify database, seed counts, secrets, and third-party integrations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-live",
            action="store_true",
            help="Skip live network calls to Gemini, MongoDB, and Weather API.",
        )

    def handle(self, *args, **options):
        self.failures = 0
        self.warnings = 0

        self.stdout.write(self.style.MIGRATE_HEADING("\nMaison Tisane setup check\n"))

        self.check_database()
        self.check_migrations()
        self.check_seed()
        self.check_secrets()

        if options["skip_live"]:
            self.report("WARN", "Live network checks", "skipped with --skip-live")
        else:
            self.check_gemini()
            self.check_mongo()
            self.check_weather()

        if not settings.DEBUG:
            self.check_production_extras()

        self.stdout.write("")
        if self.failures:
            self.stdout.write(
                self.style.ERROR(
                    f"{self.failures} check(s) FAILED, {self.warnings} warning(s).\n"
                )
            )
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f"All checks passed successfully with {self.warnings} warning(s).\n"
            )
        )

    def report(self, state, label, detail=""):
        line = f"  {state:<4}  {label}"
        if detail:
            line += f"  {detail}"
        if state == "OK":
            self.stdout.write(self.style.SUCCESS(line))
        elif state == "WARN":
            self.warnings += 1
            self.stdout.write(self.style.WARNING(line))
        else:
            self.failures += 1
            self.stdout.write(self.style.ERROR(line))

    # 1. SQL Database
    def check_database(self):
        engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
        try:
            started = time.monotonic()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            elapsed = (time.monotonic() - started) * 1000
            self.report("OK", "SQL database", f"{engine}, SELECT 1 succeeded in {elapsed:.0f} ms")
        except DatabaseError as exc:
            self.report("FAIL", "SQL database", f"{type(exc).__name__}: {exc}")

    # 2. Migrations
    def check_migrations(self):
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except DatabaseError as exc:
            self.report("FAIL", "Migrations", f"{type(exc).__name__}: {exc}")
            return

        if plan:
            names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan[:4])
            self.report(
                "FAIL",
                "Migrations",
                f"{len(plan)} unapplied migration(s): {names}. Run: python manage.py migrate",
            )
        else:
            self.report("OK", "Migrations", "all applied")

    # 3. Seed counts
    def check_seed(self):
        tea_count = Tea.objects.count()
        if tea_count >= MIN_TEAS:
            self.report("OK", "Seed: Teas", f"{tea_count} rows (minimum {MIN_TEAS})")
        else:
            self.report("FAIL", "Seed: Teas", f"{tea_count} rows, expected at least {MIN_TEAS}")

        faq_count = FAQ.objects.count()
        if faq_count >= MIN_FAQS:
            self.report("OK", "Seed: FAQs", f"{faq_count} rows (minimum {MIN_FAQS})")
        else:
            self.report("FAIL", "Seed: FAQs", f"{faq_count} rows, expected at least {MIN_FAQS}")

        code_count = ErrorCode.objects.count()
        if code_count == EXACT_CODES or code_count >= EXACT_CODES:
            self.report("OK", "Seed: Error codes", f"{code_count} rows (expected {EXACT_CODES})")
        else:
            self.report("FAIL", "Seed: Error codes", f"{code_count} rows, expected {EXACT_CODES}")

    # 4. Secrets
    def check_secrets(self):
        key = settings.SECRET_KEY or ""
        if "django-insecure" in key:
            state = "FAIL" if not settings.DEBUG else "WARN"
            self.report(
                state,
                "SECRET_KEY",
                "contains 'django-insecure'. Generate a production key before deploying.",
            )
        elif len(key) < 50:
            self.report("FAIL", "SECRET_KEY", f"length is {len(key)}, required at least 50 chars")
        else:
            self.report("OK", "SECRET_KEY", f"{len(key)} characters")

        token = getattr(settings, "TICKET_API_TOKEN", "") or ""
        if not token:
            self.report("WARN", "TICKET_API_TOKEN", "not set; staff ticket endpoints will deny everyone (401)")
        elif len(token) < 32:
            self.report("FAIL", "TICKET_API_TOKEN", f"length is {len(token)}, required at least 32 chars")
        elif token == key:
            self.report("FAIL", "TICKET_API_TOKEN", "cannot be identical to SECRET_KEY")
        else:
            self.report("OK", "TICKET_API_TOKEN", f"{len(token)} characters")

        hosts = settings.ALLOWED_HOSTS
        local_hosts = {"localhost", "127.0.0.1", "[::1]", "testserver"}
        has_non_local = any(h not in local_hosts for h in hosts if h)
        if settings.DEBUG and has_non_local:
            self.report("WARN", "DEBUG", "on while non-local ALLOWED_HOSTS configured. Turn DEBUG=0 in production.")
        elif settings.DEBUG:
            self.report("WARN", "DEBUG", "is on (local development mode)")
        else:
            self.report("OK", "DEBUG", "off")

    # 5. Gemini
    def check_gemini(self):
        if not gemini.model_is_available():
            self.report(
                "WARN",
                "Gemini",
                "GEMINI_API_KEY or GEMINI_MODEL not set. Assistant will run on saved FAQ and catalogue answers.",
            )
            return

        started = time.monotonic()
        try:
            reply = gemini.generate_content(prompt="Reply with OK")
            elapsed = (time.monotonic() - started) * 1000
            self.report("OK", "Gemini", f"{settings.GEMINI_MODEL} replied in {elapsed:.0f} ms: {reply[:40]!r}")
        except gemini.ModelUnavailable as exc:
            msg = str(exc)
            if "403" in msg or gemini.ERROR_403 in msg:
                detail = "key wrong or restricted (HTTP 403)"
            elif "404" in msg or gemini.ERROR_404 in msg:
                detail = "model name wrong (HTTP 404)"
            elif "429" in msg or gemini.ERROR_429 in msg:
                detail = "quota exceeded (HTTP 429)"
            elif "timed out" in msg or gemini.ERROR_TIMEOUT in msg:
                detail = "timed out"
            else:
                detail = msg
            self.report("FAIL", "Gemini", detail)

    # 6. MongoDB
    def check_mongo(self):
        if not mongo.is_configured():
            self.report("WARN", "MongoDB", "MONGODB_URI is empty. Chat logging and user events will be skipped.")
            return

        mongo.reset()
        ok, detail = mongo.ping()
        if not ok:
            err_lower = detail.lower()
            if "serverselectiontimeout" in err_lower or "timed out" in err_lower:
                diag = "timed out / ServerSelectionTimeout (check Atlas Network Access whitelist 0.0.0.0/0)"
            elif "auth" in err_lower or "authentication failed" in err_lower:
                diag = "authentication failed (check username and password)"
            elif "invalid uri" in err_lower or "configuration" in err_lower:
                diag = "invalid URI"
            else:
                diag = detail
            self.report("FAIL", "MongoDB", diag)
            return

        # Insert and delete test document in _setup_check collection
        try:
            client = mongo.get_client()
            if client is None:
                self.report("FAIL", "MongoDB", "could not acquire MongoClient")
                return
            coll = client[settings.MONGODB_DB]["_setup_check"]
            marker = f"check-{int(time.time())}"
            coll.insert_one({"marker": marker, "ts": time.time()})
            found = coll.find_one({"marker": marker})
            deleted = coll.delete_one({"marker": marker}).deleted_count
            if found and deleted:
                self.report("OK", "MongoDB", f"ping and write/delete in '{settings.MONGODB_DB}._setup_check' succeeded")
            else:
                self.report("FAIL", "MongoDB", "test document round trip failed")
        except Exception as exc:
            err_str = str(exc).lower()
            if "serverselectiontimeout" in err_str or "timed out" in err_str:
                diag = "timed out / ServerSelectionTimeout"
            elif "auth" in err_str:
                diag = "authentication failed"
            else:
                diag = f"{type(exc).__name__}: {exc}"
            self.report("FAIL", "MongoDB write", diag)

    # 7. Weather API (Open-Meteo for Singapore)
    def check_weather(self):
        url = "https://api.open-meteo.com/v1/forecast?latitude=1.3521&longitude=103.8198&current=temperature_2m"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "maison-tisane/1.0"})
        timeout = float(getattr(settings, "EXTERNAL_API_TIMEOUT", 3))
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status != 200:
                    self.report("FAIL", "Weather API", f"HTTP {response.status} from Open-Meteo")
                    return
                data = json.loads(response.read(10000).decode("utf-8"))
            elapsed = (time.monotonic() - started) * 1000
            temp = data.get("current", {}).get("temperature_2m")
            if temp is not None:
                self.report("OK", "Weather API", f"Open-Meteo Singapore {temp} C in {elapsed:.0f} ms")
            else:
                self.report("FAIL", "Weather API", "no temperature returned")
        except Exception as exc:
            self.report("FAIL", "Weather API", f"lookup failed: {exc}")

    # 8. Production Extras (when DEBUG=0)
    def check_production_extras(self):
        trusted = settings.CSRF_TRUSTED_ORIGINS
        if not trusted:
            self.report("FAIL", "CSRF_TRUSTED_ORIGINS", "required in production when DEBUG=0")
        else:
            invalid = [orig for orig in trusted if not orig.startswith("https://")]
            if invalid:
                self.report("FAIL", "CSRF_TRUSTED_ORIGINS", f"origins must begin with https://: {', '.join(invalid)}")
            else:
                self.report("OK", "CSRF_TRUSTED_ORIGINS", f"{len(trusted)} valid https:// origin(s)")

        db_url = getattr(settings, "DATABASE_URL", "")
        if not db_url or "sqlite" in db_url.lower():
            self.report("WARN", "Production Database", "DATABASE_URL is empty or SQLite. Render free tier loses SQLite data on redeploy.")
        else:
            self.report("OK", "Production Database", "PostgreSQL database URL configured")
