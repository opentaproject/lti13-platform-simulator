import base64
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .keys import generate_keypair, get_or_create_platform_key, public_key_to_jwk
from .models import LTIPlatformKey, LTIToolRegistration


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


class ToolRegistrationAdminImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pw12345",
        )
        self.client.force_login(self.admin)

    def _mock_urlopen(self, payload):
        response = Mock()
        response.read.return_value = payload.encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_change_list_shows_configure_by_url_link(self):
        response = self.client.get(
            reverse("admin:platform_config_ltitoolregistration_changelist")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("admin:platform_config_ltitoolregistration_configure_by_url"),
        )

    @patch("platform_config.views.urllib.request.urlopen")
    def test_configure_by_url_imports_registration(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen(
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

    @patch("platform_config.views.urllib.request.urlopen")
    def test_configure_by_url_rejects_missing_required_json_fields(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen('{"title": "OpenTA Demo"}')

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
