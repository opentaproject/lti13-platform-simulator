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


class Launch(models.Model):
    registration = models.ForeignKey(LTIToolRegistration, on_delete=models.CASCADE)
    target_link_uri = models.URLField(blank=True, null=True)
    context_id = models.CharField(max_length=255, blank=True, default="")
    context_label = models.CharField(max_length=255, blank=True, default="")
    context_title = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.target_link_uri or f"Launch {self.pk}"


class LTILaunchState(models.Model):
    state = models.CharField(max_length=255, unique=True, default=generate_token)
    nonce = models.CharField(max_length=255, default=generate_token)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    registration = models.ForeignKey(LTIToolRegistration, on_delete=models.CASCADE)
    launch = models.ForeignKey(Launch, on_delete=models.SET_NULL, null=True, blank=True)
    target_link_uri = models.URLField(blank=True, default="")
    context_id = models.CharField(max_length=255, blank=True, default="")
    context_label = models.CharField(max_length=255, blank=True, default="")
    context_title = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() - self.created_at > LAUNCH_STATE_TTL
