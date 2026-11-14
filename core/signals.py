"""
Django signals that keep MongoDB's `users` and `user_events` collections
in sync with the SQL auth tables.

Every signal handler catches all exceptions internally so a dead MongoDB
never prevents a user from signing up, logging in or logging out.
"""

import logging

from django.contrib.auth import user_logged_in, user_logged_out
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from core import mongo

log = logging.getLogger("maison")


@receiver(post_save, sender=User)
def sync_user_to_mongo(sender, instance, created, **kwargs):
    """Upsert the user document in MongoDB whenever a User row changes."""
    try:
        mongo.upsert_user(instance)
        if created:
            mongo.log_user_event(
                user_id=instance.pk,
                event="signup",
                extra={"username": instance.username},
            )
    except Exception:  # noqa: BLE001
        log.warning("mongo user sync failed for user %s", instance.pk, exc_info=True)


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    """Update last_login in MongoDB and log the event."""
    try:
        mongo.upsert_user(user)
        ip = ""
        if request is not None:
            from core.middleware import client_ip
            ip = client_ip(request)
        mongo.log_user_event(
            user_id=user.pk,
            event="login",
            ip=ip,
        )
    except Exception:  # noqa: BLE001
        log.warning("mongo login event failed for user %s", user.pk, exc_info=True)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    """Log the logout event in MongoDB."""
    if user is None:
        return
    try:
        ip = ""
        if request is not None:
            from core.middleware import client_ip
            ip = client_ip(request)
        mongo.log_user_event(
            user_id=user.pk,
            event="logout",
            ip=ip,
        )
    except Exception:  # noqa: BLE001
        log.warning("mongo logout event failed for user %s", user.pk, exc_info=True)
