from django.contrib.auth.models import User
from django.test import TestCase

from .models import UserProfile


class UserProfileSignalTests(TestCase):
    def test_creating_a_user_creates_a_profile(self):
        user = User.objects.create_user(username="alice", password="pw12345")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.role, UserProfile.STUDENT)
