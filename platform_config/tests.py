import base64

from cryptography.hazmat.primitives import serialization
from django.test import TestCase

from .keys import generate_keypair, get_or_create_platform_key, public_key_to_jwk
from .models import LTIPlatformKey


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
