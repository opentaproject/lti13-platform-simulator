import json
import subprocess
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .keys import get_or_create_platform_key, public_key_to_jwk
from .models import LTIToolRegistration


TOOL_CONFIG_FIELDS = {
    "title": {"label": "Tool title", "kind": "text", "example": "OpenTA2"},
    "target_link_uri": {
        "label": "Target link URI",
        "kind": "url",
        "example": "https://lti13.example.org/launch",
    },
    "oidc_initiation_url": {
        "label": "OIDC initiation URL",
        "kind": "url",
        "example": "https://lti13.example.org/oidc/init",
    },
    "public_jwk_url": {
        "label": "public_jwk_url syntax",
        "kind": "url",
        "example": "https://lti13.example.org/.well-known/jwks.json",
    },
}

url_validator = URLValidator(schemes=["http", "https"])


def _check(label, passed, detail):
    return {"label": label, "passed": passed, "detail": detail}


def _example_config_json():
    return json.dumps(
        {field: config["example"] for field, config in TOOL_CONFIG_FIELDS.items()},
        indent=2,
    )


def _is_valid_url(value):
    try:
        url_validator(value)
    except ValidationError:
        return False
    return True


def _validate_tool_config_payload(payload):
    checks = []

    if not isinstance(payload, dict):
        return (
            checks,
            "The JSON document must be an object with named tool config fields.",
        )

    for field, config in TOOL_CONFIG_FIELDS.items():
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

        if field == "public_jwk_url":
            detail = "Syntactically valid URL. The returned JWKS document is checked below."
        else:
            detail = "Valid URL." if config["kind"] == "url" else "Valid non-empty text."
        checks.append(_check(config["label"], True, detail))

    return checks, ""


def _fetch_config_json(config_url, timeout=10):
    try:
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                str(timeout),
                "--user-agent",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "--header",
                "Accept: application/json,text/plain,*/*",
                "--write-out",
                "\n%{http_code}",
                config_url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValidationError("Could not fetch config URL: curl is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("Could not fetch config URL: curl timed out.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ValidationError(
            f"Could not fetch config URL with curl: curl exit code {exc.returncode}: {detail}"
        ) from exc
    body, _, status_text = result.stdout.rpartition("\n")
    try:
        status_code = int(status_text)
    except ValueError as exc:
        raise ValidationError("Could not fetch config URL: curl returned an unreadable HTTP status.") from exc
    if status_code < 200 or status_code >= 300:
        detail = body.strip() or result.stderr.strip() or f"HTTP {status_code}"
        raise ValidationError(f"Config URL returned HTTP {status_code}: {detail[:1000]}")
    return body


def jwks(request):
    platform_key = get_or_create_platform_key()
    return JsonResponse({"keys": [public_key_to_jwk(platform_key)]})


def load_tool_config(config_url, timeout=10):
    payload = _fetch_config_json(config_url, timeout=timeout)
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


def _generated_registration_ids():
    return {
        "client_id": f"client-{uuid.uuid4().hex[:12]}",
        "deployment_id": f"deployment-{uuid.uuid4().hex[:12]}",
        "resource_link_id": f"resource-{uuid.uuid4().hex[:12]}",
    }


def _new_configure_context():
    return {
        "config_url": "",
        "stage_checks": [],
        "field_checks": [],
        "jwks_checks": [],
        "example_json": _example_config_json(),
        "pretty_json": "",
        "config_error": "",
        "jwks_pretty_json": "",
        "jwks_error": "",
        "config_payload": "",
        "pending_title": "",
        "saved_registration": None,
        "can_save": False,
        "has_error": False,
    }


def _validate_jwks_payload(payload):
    checks = []

    if not isinstance(payload, dict):
        return checks, "The public_jwk_url response must be a JSON object."

    keys = payload.get("keys")
    if not isinstance(keys, list):
        checks.append(_check("JWKS keys", False, "`keys` must be an array."))
        return checks, ""
    if not keys:
        checks.append(_check("JWKS keys", False, "`keys` must contain at least one key."))
        return checks, ""

    checks.append(_check("JWKS keys", True, "`keys` is a non-empty array."))

    for index, key in enumerate(keys, start=1):
        prefix = f"Key {index}"
        if not isinstance(key, dict):
            checks.append(_check(prefix, False, "Each key must be a JSON object."))
            continue

        kty = key.get("kty")
        if not isinstance(kty, str) or not kty.strip():
            checks.append(_check(f"{prefix} kty", False, "`kty` must be a non-empty string."))
            continue
        checks.append(_check(f"{prefix} kty", True, f"`kty` is {kty}."))

        kid = key.get("kid")
        if kid is not None and (not isinstance(kid, str) or not kid.strip()):
            checks.append(_check(f"{prefix} kid", False, "`kid` must be a non-empty string when present."))
        elif kid:
            checks.append(_check(f"{prefix} kid", True, "`kid` is present."))

        if kty == "RSA":
            missing = [field for field in ("n", "e") if not isinstance(key.get(field), str) or not key.get(field).strip()]
            if missing:
                checks.append(_check(f"{prefix} RSA fields", False, "Missing required RSA field(s): " + ", ".join(missing)))
            else:
                checks.append(_check(f"{prefix} RSA fields", True, "`n` and `e` are present."))
        elif kty == "EC":
            missing = [field for field in ("crv", "x", "y") if not isinstance(key.get(field), str) or not key.get(field).strip()]
            if missing:
                checks.append(_check(f"{prefix} EC fields", False, "Missing required EC field(s): " + ", ".join(missing)))
            else:
                checks.append(_check(f"{prefix} EC fields", True, "`crv`, `x`, and `y` are present."))

    return checks, ""


def _prepare_jwks_context(context, public_jwk_url):
    try:
        raw_jwks = _fetch_config_json(public_jwk_url)
    except ValidationError as exc:
        context["jwks_checks"] = [_check("Public curl access", False, exc.message)]
        context["jwks_error"] = exc.message
        context["has_error"] = True
        return False

    try:
        jwks_payload = json.loads(raw_jwks)
    except json.JSONDecodeError as exc:
        context["jwks_checks"] = [
            _check(
                "Public curl access",
                False,
                f"public_jwk_url did not return valid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.",
            )
        ]
        context["jwks_error"] = raw_jwks.strip()[:4000]
        context["has_error"] = True
        return False

    context["jwks_pretty_json"] = json.dumps(jwks_payload, indent=2, sort_keys=True)
    fetch_check = _check(
        "Public curl access",
        True,
        "public_jwk_url is publicly retrievable with curl and returned valid JSON.",
    )
    jwks_checks, jwks_error = _validate_jwks_payload(jwks_payload)
    context["jwks_checks"] = [fetch_check] + jwks_checks

    if jwks_error:
        context["jwks_checks"].append(_check("Public JWK fields", False, jwks_error))
        context["jwks_error"] = jwks_error
        context["has_error"] = True
        return False

    if any(not check["passed"] for check in jwks_checks):
        context["jwks_checks"].append(
            _check("Public JWK fields", False, "One or more public_jwk_url fields are missing or malformed.")
        )
        context["has_error"] = True
        return False

    context["jwks_checks"].append(
        _check("Public JWK fields", True, "public_jwk_url returned a sensible JWKS document.")
    )
    return True


def _prepare_validated_config_context(context, payload):
    context["pretty_json"] = json.dumps(payload, indent=2, sort_keys=True)
    context["config_payload"] = json.dumps(payload)
    context["stage_checks"].append(
        _check("Valid JSON", True, "The response is syntactically valid JSON.")
    )

    field_checks, payload_error = _validate_tool_config_payload(payload)
    context["field_checks"] = field_checks

    if payload_error:
        context["stage_checks"].append(_check("Registration object", False, payload_error))
        context["has_error"] = True
        return False

    if any(not check["passed"] for check in field_checks):
        context["stage_checks"].append(
            _check("Field formats", False, "One or more required fields are missing or malformed.")
        )
        context["has_error"] = True
        return False

    context["stage_checks"].append(
        _check("Field formats", True, "Every required field has the expected format.")
    )

    if not _prepare_jwks_context(context, payload["public_jwk_url"].strip()):
        return False

    context["pending_title"] = payload["title"].strip()
    context["can_save"] = True
    return True


def _create_registration_from_config(request, payload):
    return LTIToolRegistration.objects.create(
        **registration_kwargs_from_config(
            payload,
            issuer=request.build_absolute_uri("/").rstrip("/"),
            **_generated_registration_ids(),
        )
    )


@login_required
def configure_by_url(request):
    context = _new_configure_context()

    if request.method != "POST":
        return render(request, "platform_config/configure_by_url.html", context)

    if request.POST.get("action") == "save":
        try:
            payload = json.loads(request.POST.get("config_payload", ""))
        except json.JSONDecodeError:
            context["stage_checks"].append(
                _check("Saved JSON", False, "The pending config payload was not valid JSON.")
            )
            context["has_error"] = True
            return render(request, "platform_config/configure_by_url.html", context, status=400)

        if not _prepare_validated_config_context(context, payload):
            return render(request, "platform_config/configure_by_url.html", context, status=400)

        _create_registration_from_config(request, payload)
        return redirect("tool_list")

    config_url = request.POST.get("config_url", "").strip()
    context["config_url"] = config_url

    if not config_url:
        context["stage_checks"].append(
            _check("Configuration URL provided", False, "Enter the URL to the JSON configuration.")
        )
        context["has_error"] = True
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    if not _is_valid_url(config_url):
        context["stage_checks"].append(
            _check(
                "Configuration URL format",
                False,
                "The configuration URL must be an absolute http or https URL.",
            )
        )
        context["has_error"] = True
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    context["stage_checks"].append(
        _check("Configuration URL format", True, "The URL can be fetched over http or https.")
    )

    try:
        raw_config = _fetch_config_json(config_url)
    except ValidationError as exc:
        context["stage_checks"].append(
            _check("Fetch configuration", False, exc.message)
        )
        context["config_error"] = exc.message
        context["has_error"] = True
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
        context["config_error"] = raw_config.strip()[:4000]
        context["has_error"] = True
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    if not _prepare_validated_config_context(context, payload):
        return render(request, "platform_config/configure_by_url.html", context, status=400)

    return render(request, "platform_config/configure_by_url.html", context)
