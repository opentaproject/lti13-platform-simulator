import json
import urllib.error
import urllib.request

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from .keys import get_or_create_platform_key, public_key_to_jwk


def jwks(request):
    platform_key = get_or_create_platform_key()
    return JsonResponse({"keys": [public_key_to_jwk(platform_key)]})


def load_tool_config(config_url, timeout=10):
    request = urllib.request.Request(
        config_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            raise ValidationError(
                f"Config URL returned HTTP {exc.code}: {body[:300]}"
            ) from exc
        raise ValidationError(
            f"Config URL returned HTTP {exc.code}: {exc.reason}"
        ) from exc
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
