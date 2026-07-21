from datetime import timedelta
from unittest.mock import patch

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
        self.assertContains(response, "Saved LTI Tools")
        self.assertContains(response, "Click to Add App by ClientID")
        self.assertContains(response, "<th>pk</th>", html=True)
        self.assertContains(response, "<th>ClientID</th>", html=True)
        self.assertContains(response, "<th>deployment_id</th>", html=True)
        self.assertContains(response, "<th>delete</th>", html=True)
        self.assertContains(response, f"<td>{self.registration.pk}</td>", html=True)
        self.assertContains(response, f"<td>{self.registration.client_id}</td>", html=True)
        self.assertContains(response, f"<td>{self.registration.deployment_id}</td>", html=True)
        self.assertContains(response, f'action="/registration/{self.registration.id}/delete/"')
        self.assertContains(response, f'aria-label="Delete {self.registration.name}"')
        self.assertContains(response, 'action="/configure-by-url/"')
        self.assertContains(response, '<textarea id="config_url" name="config_url" rows="1"', html=False)

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
        self.assertContains(response, "Saved App Instance")
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, self.registration.name)
        self.assertContains(response, launch.context_id)
        self.assertContains(response, "<th>oidc_initiation_url</th>", html=True)
        self.assertContains(response, f"<td>{launch.context_id}</td>", html=True)
        self.assertContains(response, f'/launch-record/{launch.id}/oidc-init/')
        self.assertContains(response, f'action="/launch-record/{launch.id}/delete/"')
        self.assertContains(response, f'aria-label="Delete launch {launch.id}"')

    def test_delete_registration_removes_configuration(self):
        self.client.force_login(self.user)
        response = self.client.post(f"/registration/{self.registration.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        self.assertFalse(LTIToolRegistration.objects.filter(id=self.registration.id).exists())

    def test_delete_launch_removes_saved_launch(self):
        launch = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
        )
        self.client.force_login(self.user)
        response = self.client.post(f"/launch-record/{launch.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        self.assertFalse(Launch.objects.filter(id=launch.id).exists())

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
        with patch("launch.views.random.randint", return_value=472):
            response = self.client.get(f"/launch/{self.registration.id}/init/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add App by ClientID")
        self.assertContains(response, f"ClientID</strong> {self.registration.client_id}", html=False)
        self.assertNotContains(response, f"Launching {self.registration.name}")
        self.assertContains(response, "LTI Configuration")
        self.assertContains(response, "oidc_initiation_url")
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, "public_jwk_url")
        self.assertContains(response, self.registration.tool_jwks_url)
        self.assertContains(response, self.registration.target_link_uri)
        self.assertContains(response, "Editable Fields")
        self.assertContains(response, "These fields which are editable here are supplied by canvas and depend on the canvas course into which the app is installed.")
        self.assertContains(response, f'<input type="hidden" name="target_link_uri" value="{self.registration.target_link_uri}">', html=True)
        self.assertNotContains(response, 'placeholder="https://canvas.example.edu/courses/123/external_tools/456"')
        self.assertContains(response, 'name="context_id" value="cs-472-year-id"', html=False)
        self.assertContains(response, 'name="context_label" value="cs-472-year-label"', html=False)
        self.assertContains(response, 'name="context_title" value="cs-472-year-title"', html=False)
        self.assertContains(response, "A unique string identifying this target_link_uri")
        self.assertContains(response, '<button class="button-add" type="submit">Add App</button>', html=True)
        self.assertContains(response, "Save app configuration and return to the main page.")
        self.assertNotContains(response, "Continue to OIDC Init")
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

    def test_can_submit_generated_example_context_values_without_editing(self):
        self.client.force_login(self.user)
        with patch("launch.views.random.randint", return_value=472):
            response = self.client.get(f"/launch/{self.registration.id}/init/")

        post_response = self.client.post(
            f"/launch/{self.registration.id}/init/",
            {
                "target_link_uri": self.registration.target_link_uri,
                "context_id": "cs-472-year-id",
                "context_label": "cs-472-year-label",
                "context_title": "cs-472-year-title",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.url, "/")
        launch = Launch.objects.get(registration=self.registration)
        self.assertEqual(launch.context_id, "cs-472-year-id")
        self.assertEqual(launch.context_label, "cs-472-year-label")
        self.assertEqual(launch.context_title, "cs-472-year-title")
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())

    def test_get_prefills_from_registration_config_for_direct_launch_init(self):
        other_registration = make_registration(name="Other", client_id="client-456")
        Launch.objects.create(
            registration=other_registration,
            target_link_uri="https://other.openta.dev",
            context_id="other-course",
            context_label="OTHER",
            context_title="Other Course",
        )
        Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )

        self.client.force_login(self.user)
        response = self.client.get(f"/launch/{self.registration.id}/init/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.registration.target_link_uri)
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, self.registration.tool_jwks_url)
        self.assertNotContains(response, 'name="context_id" value="course-1"')
        self.assertNotContains(response, 'name="context_label" value="FFM516"')
        self.assertNotContains(response, 'name="context_title" value="Exam Grading Course"')
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

    def test_post_upserts_launch_by_client_id_and_context_id_and_returns_home(self):
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
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        existing.refresh_from_db()
        self.assertEqual(existing.context_id, "course-1")
        self.assertEqual(existing.context_label, "FFM516")
        self.assertEqual(existing.context_title, "Exam Grading Course")
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())

    def test_post_allows_same_client_id_with_different_context_id(self):
        existing = Launch.objects.create(
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
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        existing.refresh_from_db()
        self.assertEqual(existing.context_id, "course-1")
        self.assertTrue(
            Launch.objects.filter(
                registration=self.registration,
                target_link_uri="https://test7.openta.dev",
                context_id="course-2",
            ).exists()
        )
        self.assertEqual(Launch.objects.count(), 2)
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())

    def test_post_same_client_id_and_context_id_updates_target_link_uri(self):
        existing = Launch.objects.create(
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
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        existing.refresh_from_db()
        self.assertEqual(existing.target_link_uri, "https://other.openta.dev")
        self.assertEqual(existing.context_id, "course-1")
        self.assertEqual(Launch.objects.count(), 1)
        self.assertFalse(LTILaunchState.objects.filter(user=self.user, registration=self.registration).exists())

    def test_post_same_context_id_with_different_client_id_keeps_contexts_separate(self):
        other_registration = make_registration(
            name="Other",
            client_id="client-456",
            deployment_id="deploy-2",
        )
        existing = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://lti13.openta-demo.org/launch",
            context_id="course-1",
            context_label="OLD",
            context_title="Old Course",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"/launch/{other_registration.id}/init/",
            {
                "target_link_uri": "https://lti13.openta-demo.org/launch",
                "context_id": "course-1",
                "context_label": "NEW",
                "context_title": "New Course",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        existing.refresh_from_db()
        self.assertEqual(existing.registration, self.registration)
        self.assertEqual(existing.context_id, "course-1")
        self.assertEqual(existing.context_label, "OLD")
        self.assertTrue(
            Launch.objects.filter(
                registration=other_registration,
                target_link_uri="https://lti13.openta-demo.org/launch",
                context_id="course-1",
                context_label="NEW",
            ).exists()
        )
        self.assertEqual(Launch.objects.count(), 2)


class LaunchOidcInitViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="frank", password="pw12345")
        self.registration = make_registration()

    def test_saved_app_instance_click_prepares_oidc_init_payload(self):
        launch = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/launch-record/{launch.id}/oidc-init/")

        self.assertEqual(response.status_code, 200)
        launch_state = LTILaunchState.objects.get(
            user=self.user,
            registration=self.registration,
            launch=launch,
        )
        self.assertEqual(launch_state.target_link_uri, launch.target_link_uri)
        self.assertEqual(launch_state.context_id, launch.context_id)
        self.assertContains(
            response,
            f"Inspect before submitting to oidc/init for client-id = {self.registration.client_id}",
        )
        self.assertContains(response, "JSON submitted to OIDC init")
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, launch_state.state)
        self.assertContains(response, 'name="target_link_uri" value="https://test7.openta.dev"', html=False)
        self.assertContains(response, 'name="context_id" value="course-1"', html=False)


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
        launch = Launch.objects.create(
            registration=self.registration,
            target_link_uri="https://test7.openta.dev",
            context_id="course-1",
            context_label="FFM516",
            context_title="Exam Grading Course",
        )
        return LTILaunchState.objects.create(
            user=self.user,
            registration=self.registration,
            launch=launch,
            target_link_uri=launch.target_link_uri,
            context_id=launch.context_id,
            context_label=launch.context_label,
            context_title=launch.context_title,
        )

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
        self.assertContains(response, "OIDC Authorization Redirect Payload")
        self.assertContains(response, "Launch State")
        self.assertContains(response, "JWT Payload")
        self.assertContains(response, "&quot;aud&quot;: &quot;client-123&quot;")
        self.assertContains(response, "&quot;nonce&quot;: &quot;tool-nonce-xyz&quot;")
        self.assertContains(response, "&quot;id&quot;: &quot;course-1&quot;")
        self.assertFalse(LTILaunchState.objects.filter(id=launch_state.id).exists())
        self.assertTrue(Launch.objects.filter(target_link_uri="https://test7.openta.dev").exists())

    def test_unknown_login_hint_returns_400(self):
        response = self.client.get(
            "/api/lti/authorize_redirect",
            {"login_hint": "does-not-exist", "client_id": "x", "nonce": "n", "state": "s"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "OIDC Init Debug", status_code=400)
        self.assertContains(response, "Unknown or already-used login_hint", status_code=400)
        self.assertContains(response, "Request Payload", status_code=400)
        self.assertContains(response, "does-not-exist", status_code=400)

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
        self.assertContains(response, "OIDC Init Debug", status_code=400)
        self.assertContains(response, "client_id does not match", status_code=400)
        self.assertContains(response, "Launch State", status_code=400)
        self.assertContains(response, self.registration.client_id, status_code=400)
        self.assertContains(response, "wrong-client-id", status_code=400)

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
        self.assertContains(response, "OIDC Init Debug", status_code=400)
        self.assertContains(response, "Launch state has expired.", status_code=400)
        self.assertContains(response, "Launch State", status_code=400)
        self.assertContains(response, launch_state.state, status_code=400)
