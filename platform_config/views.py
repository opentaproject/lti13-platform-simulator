import json
import urllib.request

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from .keys import get_or_create_platform_key, public_key_to_jwk


def jwks(request):
    platform_key = get_or_create_platform_key()
    return JsonResponse({"keys": [public_key_to_jwk(platform_key)]})


def load_tool_config(config_url, timeout=10):
    with urllib.request.urlopen(config_url, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Config URL did not return valid JSON: {exc}") from exc


def registration_kwargs_from_config(config, *, client_id, deployment_id, issuer, resource_link_id):
    oidc_init_url = (config.get("oidc_initiation_url") or "").strip()
    target_link_uri = (config.get("target_link_uri") or "").strip()
    tool_jwks_url = (config.get("public_jwk_url") or "").strip()
    title = (config.get("title") or "").strip()

    missing = [
        key
        for key, value in (
            ("title", title),
            ("oidc_initiation_url", oidc_init_url),
            ("target_link_uri", target_link_uri),
            ("public_jwk_url", tool_jwks_url),
        )
        if not value
    ]
    if missing:
        raise ValidationError(
            "Config JSON is missing required field(s): " + ", ".join(missing)
        )

    return {
        "name": title,
        "client_id": client_id,
        "oidc_init_url": oidc_init_url,
        "launch_url": target_link_uri,
        "tool_jwks_url": tool_jwks_url,
        "target_link_uri": target_link_uri,
        "deployment_id": deployment_id,
        "issuer": issuer,
        "resource_link_id": resource_link_id,
    }
