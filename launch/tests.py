from datetime import timedelta

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from platform_config.models import LTIToolRegistration
from platform_config.keys import get_or_create_platform_key

from .models import UserProfile, LTILaunchState
from .jwt_utils import build_claims, sign_launch_jwt


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


class ToolListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carol", password="pw12345")
        self.registration = make_registration()

    def test_requires_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_lists_registrations_when_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.registration.name)


class LaunchInitViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dave", password="pw12345")
        self.registration = make_registration()

    def test_creates_launch_state_and_renders_auto_submit_form(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/launch/{self.registration.id}/init/")
        self.assertEqual(response.status_code, 200)

        launch_state = LTILaunchState.objects.get(user=self.user, registration=self.registration)
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, launch_state.state)
        self.assertContains(response, self.registration.client_id)


class JwtClaimTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="instructor1",
            email="instructor1@example.org",
            first_name="Ines",
            last_name="Tructor",
        )
        self.user.profile.role = UserProfile.INSTRUCTOR
        self.user.profile.save()
        self.registration = make_registration()

    def test_build_claims_contains_required_fields(self):
        claims = build_claims(self.user, self.registration, tool_nonce="tool-nonce-1")
        self.assertEqual(claims["iss"], self.registration.issuer)
        self.assertEqual(claims["sub"], str(self.user.id))
        self.assertEqual(claims["aud"], self.registration.client_id)
        self.assertEqual(claims["nonce"], "tool-nonce-1")
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/message_type"],
            "LtiResourceLinkRequest",
        )
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/roles"],
            ["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        )
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/resource_link"],
            {"id": self.registration.resource_link_id},
        )
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/context"],
            {
                "id": self.registration.context_id,
                "label": self.registration.context_label,
                "title": self.registration.context_title,
            },
        )
        self.assertEqual(claims["email"], "instructor1@example.org")
        self.assertEqual(claims["given_name"], "Ines")
        self.assertEqual(claims["family_name"], "Tructor")

    def test_student_role_maps_to_learner(self):
        self.user.profile.role = UserProfile.STUDENT
        self.user.profile.save()
        claims = build_claims(self.user, self.registration, tool_nonce="n")
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/roles"],
            ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
        )

    def test_sign_launch_jwt_is_verifiable_with_the_published_public_key(self):
        token = sign_launch_jwt(self.user, self.registration, tool_nonce="tool-nonce-1")
        platform_key = get_or_create_platform_key()
        public_key = serialization.load_pem_public_key(
            platform_key.public_key_pem.encode("utf-8")
        )

        decoded = pyjwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=self.registration.client_id,
        )
        self.assertEqual(decoded["sub"], str(self.user.id))
        self.assertEqual(decoded["nonce"], "tool-nonce-1")

        header = pyjwt.get_unverified_header(token)
        self.assertEqual(header["kid"], platform_key.kid)


class AuthCallbackViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="erin", password="pw12345")
        self.registration = make_registration()

    def _create_launch_state(self):
        self.client.force_login(self.user)
        self.client.get(f"/launch/{self.registration.id}/init/")
        return LTILaunchState.objects.get(user=self.user, registration=self.registration)

    def test_valid_callback_signs_and_posts_jwt_then_deletes_state(self):
        launch_state = self._create_launch_state()

        response = self.client.get(
            "/api/lti/authorize_redirect",
            {
                "login_hint": launch_state.state,
                "client_id": self.registration.client_id,
                "nonce": "tool-nonce-xyz",
                "state": "tool-state-xyz",
                "redirect_uri": self.registration.launch_url,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.registration.launch_url)
        self.assertContains(response, "tool-state-xyz")
        self.assertFalse(LTILaunchState.objects.filter(id=launch_state.id).exists())

    def test_unknown_login_hint_returns_400(self):
        response = self.client.get(
            "/api/lti/authorize_redirect",
            {"login_hint": "does-not-exist", "client_id": "x", "nonce": "n", "state": "s"},
        )
        self.assertEqual(response.status_code, 400)

    def test_client_id_mismatch_returns_400(self):
        launch_state = self._create_launch_state()
        response = self.client.get(
            "/api/lti/authorize_redirect",
            {
                "login_hint": launch_state.state,
                "client_id": "wrong-client-id",
                "nonce": "n",
                "state": "s",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_expired_launch_state_returns_400(self):
        launch_state = self._create_launch_state()
        launch_state.created_at = timezone.now() - timedelta(minutes=10)
        launch_state.save(update_fields=["created_at"])

        response = self.client.get(
            "/api/lti/authorize_redirect",
            {
                "login_hint": launch_state.state,
                "client_id": self.registration.client_id,
                "nonce": "n",
                "state": "s",
            },
        )
        self.assertEqual(response.status_code, 400)
