import base64
import json
import subprocess
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .keys import generate_keypair, get_or_create_platform_key, public_key_to_jwk
from .models import LTIPlatformKey, LTIToolRegistration
from .views import _fetch_config_json


def b64url_to_int(value):
    padded = value + "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


class KeyGenerationTests(TestCase):
    def test_generate_keypair_produces_matching_private_and_public_key(self):
        private_pem, public_pem = generate_keypair()
        private_key = serialization.load_pem_private_key(
            private_pem.encode("utf-8"), password=None
        )
        public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
        self.assertEqual(private_key.key_size, 2048)
        self.assertEqual(
            private_key.public_key().public_numbers(), public_key.public_numbers()
        )

    def test_get_or_create_platform_key_creates_only_once(self):
        self.assertEqual(LTIPlatformKey.objects.count(), 0)
        key_one = get_or_create_platform_key()
        key_two = get_or_create_platform_key()
        self.assertEqual(key_one.id, key_two.id)
        self.assertEqual(LTIPlatformKey.objects.count(), 1)

    def test_public_key_to_jwk_round_trip(self):
        key = get_or_create_platform_key()
        jwk = public_key_to_jwk(key)
        public_key = serialization.load_pem_public_key(
            key.public_key_pem.encode("utf-8")
        )
        numbers = public_key.public_numbers()

        self.assertEqual(b64url_to_int(jwk["n"]), numbers.n)
        self.assertEqual(b64url_to_int(jwk["e"]), numbers.e)
        self.assertEqual(jwk["kid"], key.kid)
        self.assertEqual(jwk["kty"], "RSA")
        self.assertEqual(jwk["alg"], "RS256")


class JwksViewTests(TestCase):
    def test_jwks_endpoint_returns_one_rsa_key(self):
        response = self.client.get("/jwks.json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["keys"]), 1)
        self.assertEqual(data["keys"][0]["kty"], "RSA")


class FetchConfigJsonTests(TestCase):
    @patch("platform_config.views.subprocess.run")
    def test_non_2xx_response_includes_http_status_and_body(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout="Forbidden by proxy\n403",
            stderr="",
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Config URL returned HTTP 403: Forbidden by proxy",
        ):
            _fetch_config_json("https://tool.example.org/lti/config.json")

    @patch("platform_config.views.subprocess.run")
    def test_curl_failure_includes_curl_exit_code_and_error_text(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=60,
            cmd=["curl"],
            stderr="SSL certificate problem: unable to get local issuer certificate",
        )

        with self.assertRaisesMessage(
            ValidationError,
            "Could not fetch config URL with curl: curl exit code 60: SSL certificate problem",
        ):
            _fetch_config_json("https://tool.example.org/lti/config.json")


class ToolRegistrationAdminImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pw12345",
        )
        self.client.force_login(self.admin)

    def test_change_list_shows_configure_by_url_link(self):
        response = self.client.get(
            reverse("admin:platform_config_ltitoolregistration_changelist")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("admin:platform_config_ltitoolregistration_configure_by_url"),
        )

    def test_admin_list_displays_registration_pk(self):
        registration = LTIToolRegistration.objects.create(
            name="OpenTA Demo",
            client_id="client-123",
            oidc_init_url="https://lti13.openta-demo.org/oidc/init",
            launch_url="https://lti13.openta-demo.org/launch",
            tool_jwks_url="https://lti13.openta-demo.org/.well-known/jwks.json",
            target_link_uri="https://lti13.openta-demo.org/launch",
            deployment_id="deployment-123",
            issuer="http://testserver",
            resource_link_id="resource-123",
        )

        response = self.client.get(
            reverse("admin:platform_config_ltitoolregistration_changelist")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(registration.pk))

    @patch("platform_config.views._fetch_config_json")
    def test_configure_by_url_imports_registration(self, mock_fetch_config_json):
        mock_fetch_config_json.return_value = (
            """
            {
              "title": "OpenTA Demo",
              "target_link_uri": "https://lti13.openta-demo.org/launch",
              "oidc_initiation_url": "https://lti13.openta-demo.org/oidc/init",
              "public_jwk_url": "https://lti13.openta-demo.org/.well-known/jwks.json"
            }
            """
        )

        response = self.client.post(
            reverse("admin:platform_config_ltitoolregistration_configure_by_url"),
            {
                "config_url": "https://lti13.openta-demo.org/lti13/config.json",
                "client_id": "client-123",
                "deployment_id": "deployment-123",
                "resource_link_id": "resource-123",
            },
        )

        registration = LTIToolRegistration.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(registration.name, "OpenTA Demo")
        self.assertEqual(registration.client_id, "client-123")
        self.assertEqual(
            registration.oidc_init_url, "https://lti13.openta-demo.org/oidc/init"
        )
        self.assertEqual(registration.launch_url, "https://lti13.openta-demo.org/launch")
        self.assertEqual(
            registration.tool_jwks_url,
            "https://lti13.openta-demo.org/.well-known/jwks.json",
        )
        self.assertEqual(registration.target_link_uri, registration.launch_url)
        self.assertEqual(registration.deployment_id, "deployment-123")
        self.assertEqual(registration.resource_link_id, "resource-123")
        self.assertEqual(registration.issuer, "http://testserver")

    @patch("platform_config.views._fetch_config_json")
    def test_configure_by_url_rejects_missing_required_json_fields(self, mock_fetch_config_json):
        mock_fetch_config_json.return_value = '{"title": "OpenTA Demo"}'

        response = self.client.post(
            reverse("admin:platform_config_ltitoolregistration_configure_by_url"),
            {
                "config_url": "https://lti13.openta-demo.org/lti13/config.json",
                "client_id": "client-123",
                "deployment_id": "deployment-123",
                "resource_link_id": "resource-123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Config JSON is missing required field(s): oidc_initiation_url, target_link_uri, public_jwk_url",
        )
        self.assertEqual(LTIToolRegistration.objects.count(), 0)
class ConfigureByUrlViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="pw12345")

    def _valid_payload(self, **overrides):
        payload = {
            "title": "OpenTA2",
            "target_link_uri": "https://lti13.example.org/launch",
            "oidc_initiation_url": "https://lti13.example.org/oidc/init",
            "public_jwk_url": "https://lti13.example.org/.well-known/jwks.json",
        }
        payload.update(overrides)
        return payload

    def _valid_jwks_payload(self, **overrides):
        payload = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "tool-key-1",
                    "n": "abc123",
                    "e": "AQAB",
                }
            ]
        }
        payload.update(overrides)
        return payload

    def test_requires_login(self):
        response = self.client.get("/configure-by-url/")
        self.assertEqual(response.status_code, 302)

    def test_get_renders_configuration_form(self):
        self.client.force_login(self.user)
        response = self.client.get("/configure-by-url/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configure Tool By URL")
        self.assertContains(response, 'name="config_url"')

    def test_post_valid_json_and_fields_previews_registration_without_saving(self):
        self.client.force_login(self.user)
        with patch(
            "platform_config.views._fetch_config_json",
            side_effect=[
                json.dumps(self._valid_payload()),
                json.dumps(self._valid_jwks_payload()),
            ],
        ):
            response = self.client.post(
                "/configure-by-url/",
                {"config_url": "https://tool.example.org/lti/config.json"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(LTIToolRegistration.objects.count(), 0)
        self.assertContains(response, "<td>Valid JSON</td>", html=True)
        self.assertContains(response, '<td class="status-pass">PASS</td>', html=True)
        self.assertContains(response, "<td>Field formats</td>", html=True)
        self.assertContains(response, "Returned JSON")
        self.assertContains(response, "oidc_initiation_url")
        self.assertContains(response, "<td>public_jwk_url syntax</td>", html=True)
        self.assertContains(response, "Syntactically valid URL. The returned JWKS document is checked below.")
        self.assertContains(response, "public_jwk_url Check")
        self.assertContains(response, "Returned public_jwk_url JSON")
        self.assertContains(response, "<td>Public curl access</td>", html=True)
        self.assertContains(response, "public_jwk_url is publicly retrievable with curl and returned valid JSON.")
        self.assertContains(response, "<td>Public JWK fields</td>", html=True)
        checklist_html = response.content.decode().split("<h2>Returned JSON</h2>")[0]
        self.assertNotIn("Fetch public_jwk_url", checklist_html)
        self.assertContains(response, "tool-key-1")
        self.assertContains(response, "Created OpenTA2")
        self.assertContains(response, "Save")
        self.assertContains(response, "Cancel")

    def test_save_valid_preview_payload_creates_registration_and_redirects_home(self):
        self.client.force_login(self.user)
        with patch(
            "platform_config.views._fetch_config_json",
            return_value=json.dumps(self._valid_jwks_payload()),
        ):
            response = self.client.post(
                "/configure-by-url/",
                {
                    "action": "save",
                    "config_payload": json.dumps(self._valid_payload()),
                },
            )

        self.assertEqual(response.status_code, 302)
        registration = LTIToolRegistration.objects.get()
        self.assertEqual(registration.name, "OpenTA2")
        self.assertEqual(registration.oidc_init_url, "https://lti13.example.org/oidc/init")
        self.assertEqual(registration.launch_url, "https://lti13.example.org/launch")
        self.assertTrue(registration.client_id.startswith("client-"))
        self.assertEqual(response.url, "/")

    def test_post_valid_config_blocks_save_when_public_jwk_url_is_not_jwks(self):
        self.client.force_login(self.user)
        with patch(
            "platform_config.views._fetch_config_json",
            side_effect=[
                json.dumps(self._valid_payload()),
                json.dumps({"not_keys": []}),
            ],
        ):
            response = self.client.post(
                "/configure-by-url/",
                {"config_url": "https://tool.example.org/lti/config.json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(LTIToolRegistration.objects.exists())
        self.assertContains(response, "<td>Valid JSON</td>", status_code=400, html=True)
        self.assertContains(response, "public_jwk_url Check", status_code=400)
        self.assertContains(response, "Returned public_jwk_url JSON", status_code=400)
        self.assertContains(response, "<td>Public JWK fields</td>", status_code=400, html=True)
        self.assertContains(response, '<td class="status-fail">FAIL</td>', status_code=400, html=True)
        self.assertContains(response, "`keys` must be an array.", status_code=400)
        self.assertContains(response, "Cancel", status_code=400)

    def test_post_valid_config_shows_public_jwk_url_fetch_error(self):
        self.client.force_login(self.user)
        with patch(
            "platform_config.views._fetch_config_json",
            side_effect=[
                json.dumps(self._valid_payload()),
                ValidationError("Config URL returned HTTP 500: upstream error body"),
            ],
        ):
            response = self.client.post(
                "/configure-by-url/",
                {"config_url": "https://tool.example.org/lti/config.json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(LTIToolRegistration.objects.exists())
        self.assertContains(response, "public_jwk_url Check", status_code=400)
        self.assertContains(response, "public_jwk_url Error", status_code=400)
        self.assertContains(response, "<td>Public curl access</td>", status_code=400, html=True)
        self.assertContains(response, "upstream error body", status_code=400)
        self.assertContains(response, "Cancel", status_code=400)

    def test_post_invalid_json_returns_example_and_does_not_save(self):
        self.client.force_login(self.user)
        with patch(
            "platform_config.views._fetch_config_json",
            return_value='not-json from upstream',
        ):
            response = self.client.post(
                "/configure-by-url/",
                {"config_url": "https://tool.example.org/lti/config.json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(LTIToolRegistration.objects.exists())
        self.assertContains(response, "<td>Valid JSON</td>", status_code=400, html=True)
        self.assertContains(response, '<td class="status-fail">FAIL</td>', status_code=400, html=True)
        self.assertContains(response, "Configuration URL Error", status_code=400)
        self.assertContains(response, "not-json from upstream", status_code=400)
        self.assertContains(response, "Example JSON", status_code=400)
        self.assertContains(response, "oidc_initiation_url", status_code=400)
        self.assertContains(response, "Cancel", status_code=400)

    def test_post_config_url_fetch_error_shows_returned_status_and_body(self):
        self.client.force_login(self.user)
        with patch(
            "platform_config.views._fetch_config_json",
            side_effect=ValidationError("Config URL returned HTTP 403: cloudflare blocked"),
        ):
            response = self.client.post(
                "/configure-by-url/",
                {"config_url": "https://tool.example.org/lti/config.json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(LTIToolRegistration.objects.exists())
        self.assertContains(response, "Fetch configuration", status_code=400)
        self.assertContains(response, "Configuration URL Error", status_code=400)
        self.assertContains(response, "HTTP 403", status_code=400)
        self.assertContains(response, "cloudflare blocked", status_code=400)
        self.assertContains(response, "Cancel", status_code=400)

    def test_post_malformed_field_reports_field_failure_and_does_not_save(self):
        self.client.force_login(self.user)
        payload = self._valid_payload(oidc_initiation_url="not-a-url", title="")
        with patch(
            "platform_config.views._fetch_config_json",
            return_value=json.dumps(payload),
        ):
            response = self.client.post(
                "/configure-by-url/",
                {"config_url": "https://tool.example.org/lti/config.json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(LTIToolRegistration.objects.exists())
        self.assertContains(response, "<td>Valid JSON</td>", status_code=400, html=True)
        self.assertContains(response, "Returned JSON", status_code=400)
        self.assertContains(response, "<td>OIDC initiation URL</td>", status_code=400, html=True)
        self.assertContains(response, "`oidc_initiation_url` must be an absolute http or https URL.", status_code=400)
        self.assertContains(response, "<td>Tool title</td>", status_code=400, html=True)
        self.assertContains(response, "`title` cannot be blank.", status_code=400)
        self.assertContains(response, "Cancel", status_code=400)
