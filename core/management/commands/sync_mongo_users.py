"""
Management command to sync all Django auth users to MongoDB 'users' collection.

    python manage.py sync_mongo_users
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core import mongo


class Command(BaseCommand):
    help = "Sync all Django auth users into the MongoDB 'users' collection."

    def handle(self, *args, **options):
        if not mongo.is_configured():
            self.stdout.write(self.style.ERROR("MONGODB_URI is not configured in .env"))
            return

        mongo.reset()
        users = list(User.objects.all())
        if not users:
            self.stdout.write(
                self.style.WARNING(
                    "No users found in Django SQL database yet. "
                    "Register a user at http://localhost:8000/accounts/register/ "
                    "or run 'python manage.py createsuperuser'."
                )
            )
            return

        success = 0
        for user in users:
            ok = mongo.upsert_user(user)
            if ok:
                success += 1
                self.stdout.write(self.style.SUCCESS(f"Synced user '{user.username}' (ID {user.pk}) to MongoDB."))
            else:
                self.stdout.write(self.style.ERROR(f"Failed to sync user '{user.username}' to MongoDB."))

        self.stdout.write(self.style.SUCCESS(f"\nDone: {success}/{len(users)} user(s) synced to MongoDB."))
