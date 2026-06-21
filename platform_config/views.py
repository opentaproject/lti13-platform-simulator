from django.http import JsonResponse

from .keys import get_or_create_platform_key, public_key_to_jwk


def jwks(request):
    platform_key = get_or_create_platform_key()
    return JsonResponse({"keys": [public_key_to_jwk(platform_key)]})
