from datetime import timedelta

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from platform_config.models import LTIToolRegistration
from platform_config.keys import get_or_create_platform_key

from .models import Launch, UserProfile, LTILaunchState
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


class LaunchModelTests(TestCase):
    def setUp(self):
        self.registration = make_registration()

    def test_target_link_uri_allows_blank_and_null(self):
        launch_one = Launch.objects.create(registration=self.registration, target_link_uri=None)
        launch_two = Launch.objects.create(registration=self.registration, target_link_uri=None)
        self.assertIsNone(launch_one.target_link_uri)
        self.assertIsNone(launch_two.target_link_uri)


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

    def test_lists_saved_launches_with_links(self):
        launch = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, launch.target_link_uri)
        self.assertContains(response, self.registration.name)
        self.assertContains(response, launch.context_id)
        self.assertContains(response, f'/launch/{self.registration.id}/init/?launch={launch.id}')

    def test_logout_works_via_post(self):
        self.client.force_login(self.user)
        response = self.client.post("/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login/")


class LaunchInitViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dave", password="pw12345")
        self.registration = make_registration()

    def test_renders_context_form_on_get(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/launch/{self.registration.id}/init/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.username)
        self.assertContains(response, self.user.profile.role)
        self.assertContains(response, "The destination URL the tool should treat as this launch target")
        self.assertContains(response, "A unique string identifying this target_link_uri")
        self.assertContains(response, 'name="context_id"')
        self.assertContains(response, 'name="context_label"')
        self.assertContains(response, 'name="context_title"')
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())

    def test_renders_context_fields_from_query_params(self):
        self.client.force_login(self.user)
        response = self.client.get(
            f"/launch/{self.registration.id}/init/",
            {
                "context_id": "course-1",
                "context_label": "FFM516",
                "context_title": "Exam Grading Course",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="context_id"')
        self.assertContains(response, "course-1")
        self.assertContains(response, 'name="context_label"')
        self.assertContains(response, "FFM516")
        self.assertContains(response, 'name="context_title"')
        self.assertContains(response, "Exam Grading Course")

    def test_get_prefills_from_most_recent_launch_for_registration(self):
        other_registration = make_registration(name="Other", client_id="client-456")
        Launch.objects.create(
            registration=other_registration,
            target_link_uri="https://other.openta.dev",
            context_id="other-course",
            context_label="OTHER",
            context_title="Other Course",
        )
        latest = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )

        self.client.force_login(self.user)
        response = self.client.get(f"/launch/{self.registration.id}/init/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, latest.target_link_uri)
        self.assertContains(response, latest.context_id)
        self.assertContains(response, latest.context_label)
        self.assertContains(response, latest.context_title)
        self.assertNotContains(response, "https://other.openta.dev")

    def test_get_prefills_from_selected_launch(self):
        selected = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )
        Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://other.openta.dev",
            context_id="course-2",
            context_label="OTHER",
            context_title="Other Course",
        )

        self.client.force_login(self.user)
        response = self.client.get(f"/launch/{self.registration.id}/init/?launch={selected.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, selected.target_link_uri)
        self.assertContains(response, selected.context_id)
        self.assertContains(response, selected.context_label)
        self.assertContains(response, selected.context_title)
        self.assertNotContains(response, "https://other.openta.dev")

    def test_post_upserts_launch_by_target_link_uri_and_creates_launch_state(self):
        existing = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="OLD",
            context_title="Old Title",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            f"/launch/{self.registration.id}/init/",
            {
                "target_link_uri": "https://test7.openta.dev",
                "context_id": "course-1",
                "context_label": "FFM516",
                "context_title": "Exam Grading Course",
            },
        )
        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        self.assertEqual(existing.context_id, "course-1")
        self.assertEqual(existing.context_label, "FFM516")
        self.assertEqual(existing.context_title, "Exam Grading Course")
        launch_state = LTILaunchState.objects.get(user=self.user, registration=self.registration)
        self.assertEqual(launch_state.launch_id, existing.pk)
        self.assertEqual(launch_state.target_link_uri, "https://test7.openta.dev")
        self.assertEqual(launch_state.context_id, "course-1")
        self.assertEqual(launch_state.context_label, "FFM516")
        self.assertEqual(launch_state.context_title, "Exam Grading Course")
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, launch_state.state)
        self.assertContains(response, self.registration.client_id)

    def test_post_rejects_target_link_uri_collision_with_different_context_id(self):
        Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            f"/launch/{self.registration.id}/init/",
            {
                "target_link_uri": "https://test7.openta.dev",
                "context_id": "course-2",
                "context_label": "NEW",
                "context_title": "New Course",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Collision: target_link_uri https://test7.openta.dev is already bound to context_id course-1.",
            status_code=400,
        )
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())

    def test_post_rejects_context_id_collision_with_different_target_link_uri(self):
        Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            f"/launch/{self.registration.id}/init/",
            {
                "target_link_uri": "https://other.openta.dev",
                "context_id": "course-1",
                "context_label": "FFM516",
                "context_title": "Exam Grading Course",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Collision: context_id course-1 is already bound to target_link_uri https://test7.openta.dev.",
            status_code=400,
        )
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())


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
        claims = build_claims(
            self.user,
            self.registration,
            tool_nonce="tool-nonce-1",
            target_link_uri="https://test7.openta.dev",
            context={
                "id": "course-1",
                "label": "FFM516",
                "title": "Exam Grading Course",
            },
        )
        self.assertEqual(claims["iss"], self.registration.issuer)
        self.assertEqual(claims["sub"], str(self.user.id))
        self.assertEqual(claims["aud"], self.registration.client_id)
        self.assertEqual(claims["nonce"], "tool-nonce-1")
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/target_link_uri"],
            "https://test7.openta.dev",
        )
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
                "id": "course-1",
                "label": "FFM516",
                "title": "Exam Grading Course",
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
        self.client.post(
            f"/launch/{self.registration.id}/init/",
            {
                "target_link_uri": "https://test7.openta.dev",
                "context_id": "course-1",
                "context_label": "FFM516",
                "context_title": "Exam Grading Course",
            },
        )
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
        self.assertTrue(Launch.objects.filter(target_link_uri="https://test7.openta.dev").exists())

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
