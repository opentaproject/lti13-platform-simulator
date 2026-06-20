import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from platform_config.models import LTIToolRegistration

LAUNCH_STATE_TTL = timedelta(minutes=5)


def generate_token():
    return secrets.token_urlsafe(32)


class UserProfile(models.Model):
    INSTRUCTOR = "instructor"
    STUDENT = "student"
    ROLE_CHOICES = [(INSTRUCTOR, "Instructor"), (STUDENT, "Student")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=STUDENT)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class LTILaunchState(models.Model):
    state = models.CharField(max_length=255, unique=True, default=generate_token)
    nonce = models.CharField(max_length=255, default=generate_token)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    registration = models.ForeignKey(LTIToolRegistration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() - self.created_at > LAUNCH_STATE_TTL
