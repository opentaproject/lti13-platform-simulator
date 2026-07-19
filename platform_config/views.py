import json
import urllib.error
import urllib.request
from django.core.exceptions import ValidationError
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from django.shortcuts import render

from .keys import get_or_create_platform_key, public_key_to_jwk
from .models import LTIToolRegistration


CONFIG_FIELDS = {
    "name": {"label": "Tool name", "kind": "text", "example": "OpenTA2"},
    "client_id": {"label": "Client ID", "kind": "text", "example": "client-123"},
    "oidc_init_url": {
        "label": "OIDC init URL",
        "kind": "url",
        "example": "https://lti13.example.org/oidc/init",
    },
    "launch_url": {
        "label": "Launch URL",
        "kind": "url",
        "example": "https://lti13.example.org/launch",
    },
    "tool_jwks_url": {
        "label": "Tool JWKS URL",
        "kind": "url",
        "example": "https://lti13.example.org/.well-known/jwks.json",
    },
    "target_link_uri": {
        "label": "Target link URI",
        "kind": "url",
        "example": "https://lti13.example.org/launch",
    },
    "deployment_id": {"label": "Deployment ID", "kind": "text", "example": "deploy-1"},
    "issuer": {
        "label": "Issuer",
        "kind": "url",
        "example": "https://simulator.example.org",
    },
    "resource_link_id": {
        "label": "Resource link ID",
        "kind": "text",
        "example": "resource-1",
    },
}

url_validator = URLValidator(schemes=["http", "https"])


def _check(label, passed, detail):
    return {"label": label, "passed": passed, "detail": detail}


def _example_config_json():
    return json.dumps(
        {field: config["example"] for field, config in CONFIG_FIELDS.items()},
        indent=2,
    )


def _is_valid_url(value):
    try:
        url_validator(value)
    except ValidationError:
        return False
    return True


def _validate_config_payload(payload):
    checks = []
    cleaned = {}

    if not isinstance(payload, dict):
        return (
            checks,
            cleaned,
            "The JSON document must be an object with named registration fields.",
        )

    for field, config in CONFIG_FIELDS.items():
        value = payload.get(field)
        if value is None:
            checks.append(
                _check(config["label"], False, f"Missing required field `{field}`.")
            )
            continue
        if not isinstance(value, str):
            checks.append(
                _check(config["label"], False, f"`{field}` must be a string.")
            )
            continue

        value = value.strip()
        if not value:
            checks.append(
                _check(config["label"], False, f"`{field}` cannot be blank.")
            )
            continue

        if config["kind"] == "url" and not _is_valid_url(value):
            checks.append(
                _check(
                    config["label"],
                    False,
                    f"`{field}` must be an absolute http or https URL.",
                )
            )
            continue

        cleaned[field] = value
        detail = "Valid URL." if config["kind"] == "url" else "Valid non-empty text."
        checks.append(_check(config["label"], True, detail))

    return checks, cleaned, ""


def _fetch_config_json(config_url):
    with urlopen(config_url, timeout=10) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset)


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
@login_required
def configure_by_url(request):
    context = {
        "config_url": "",
        "stage_checks": [],
        "field_checks": [],
        "example_json": _example_config_json(),
    }

    if request.method != "POST":
        return render(request, "platform_config/configure_by_url.html", context)

    config_url = request.POST.get("config_url", "").strip()
    context["config_url"] = config_url

    if not config_url:
        context["stage_checks"].append(
            _check("Configuration URL provided", False, "Enter the URL to the JSON configuration.")
        )
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    if not _is_valid_url(config_url):
        context["stage_checks"].append(
            _check(
                "Configuration URL format",
                False,
                "The configuration URL must be an absolute http or https URL.",
            )
        )
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    context["stage_checks"].append(
        _check("Configuration URL format", True, "The URL can be fetched over http or https.")
    )

    try:
        raw_config = _fetch_config_json(config_url)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        context["stage_checks"].append(
            _check("Fetch configuration", False, f"Could not fetch the URL: {exc}")
        )
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    context["stage_checks"].append(
        _check("Fetch configuration", True, "The configuration document was fetched.")
    )

    try:
        payload = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        context["stage_checks"].append(
            _check("Valid JSON", False, f"JSON parse error at line {exc.lineno}, column {exc.colno}: {exc.msg}.")
        )
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    context["stage_checks"].append(
        _check("Valid JSON", True, "The response is syntactically valid JSON.")
    )

    field_checks, cleaned, payload_error = _validate_config_payload(payload)
    context["field_checks"] = field_checks

    if payload_error:
        context["stage_checks"].append(_check("Registration object", False, payload_error))
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    if any(not check["passed"] for check in field_checks):
        context["stage_checks"].append(
            _check("Field formats", False, "One or more required fields are missing or malformed.")
        )
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    context["stage_checks"].append(
        _check("Field formats", True, "Every required field has the expected format.")
    )
    registration = LTIToolRegistration.objects.create(**cleaned)
    context["stage_checks"].append(
        _check("Registration saved", True, f"Created registration #{registration.pk}.")
    )
    context["registration"] = registration
    return render(request, "platform_config/configure_by_url.html", context)
