from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from platform_config.models import LTIToolRegistration

from .models import UserProfile, LTILaunchState


class UserProfileSignalTests(TestCase):
    def test_creating_a_user_creates_a_profile(self):
        user = User.objects.create_user(username="alice", password="pw12345")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.role, UserProfile.STUDENT)


def make_registration(**overrides):
    defaults = dict(
        name="OpenTA2",
        client_id="client-123",
        oidc_init_url="https://lti13.openta-demo.org/oidc/init",
        launch_url="https://lti13.openta-demo.org/launch",
        tool_jwks_url="https://lti13.openta-demo.org/.well-known/jwks.json",
        target_link_uri="https://lti13.openta-demo.org/launch",
        deployment_id="deploy-1",
        issuer="https://simulator.example.org",
        context_id="course-1",
        context_label="FFM516",
        context_title="Exam Grading Course",
        resource_link_id="resource-1",
    )
    defaults.update(overrides)
    return LTIToolRegistration.objects.create(**defaults)


class LTILaunchStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="pw12345")
        self.registration = make_registration()

    def test_state_and_nonce_are_auto_generated_and_unique(self):
        state_one = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        state_two = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        self.assertTrue(state_one.state)
        self.assertTrue(state_one.nonce)
        self.assertNotEqual(state_one.state, state_two.state)

    def test_is_expired_false_when_fresh(self):
        state = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        self.assertFalse(state.is_expired())

    def test_is_expired_true_after_ttl(self):
        state = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        state.created_at = timezone.now() - timedelta(minutes=10)
        state.save(update_fields=["created_at"])
        self.assertTrue(state.is_expired())
