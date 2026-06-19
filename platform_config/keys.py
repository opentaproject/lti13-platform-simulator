import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .models import LTIPlatformKey

DEFAULT_KID = "platform-key-1"


def generate_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def get_or_create_platform_key():
    key = LTIPlatformKey.objects.first()
    if key is not None:
        return key
    private_pem, public_pem = generate_keypair()
    return LTIPlatformKey.objects.create(
        kid=DEFAULT_KID, private_key_pem=private_pem, public_key_pem=public_pem
    )


def _int_to_base64url(value):
    byte_length = (value.bit_length() + 7) // 8
    value_bytes = value.to_bytes(byte_length, "big")
    return base64.urlsafe_b64encode(value_bytes).rstrip(b"=").decode("ascii")


def public_key_to_jwk(platform_key):
    public_key = serialization.load_pem_public_key(
        platform_key.public_key_pem.encode("utf-8")
    )
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": platform_key.kid,
        "n": _int_to_base64url(numbers.n),
        "e": _int_to_base64url(numbers.e),
    }
