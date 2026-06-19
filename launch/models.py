from django.conf import settings
from django.db import models


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
