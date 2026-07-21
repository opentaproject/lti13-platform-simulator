import json
import logging
import random
import traceback

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.views.decorators.http import require_POST

from platform_config.models import LTIToolRegistration
from .models import Launch, LTILaunchState
from .jwt_utils import build_claims, sign_claims

logger = logging.getLogger(__name__)


def _pretty_json(value):
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _request_payload(request):
    return {
        "method": request.method,
        "path": request.path,
        "query_string": request.META.get("QUERY_STRING", ""),
        "GET": request.GET.dict(),
        "POST": request.POST.dict(),
        "headers": {
            key[5:].replace("_", "-").title(): value
            for key, value in request.META.items()
            if key.startswith("HTTP_") and key not in {"HTTP_COOKIE"}
        },
    }


def _launch_state_payload(launch_state):
    if not launch_state:
        return {}
    registration = launch_state.registration
    launch = launch_state.launch
    return {
        "state_pk": launch_state.pk,
        "state": launch_state.state,
        "nonce": launch_state.nonce,
        "created_at": launch_state.created_at,
        "is_expired": launch_state.is_expired(),
        "registration": {
            "pk": registration.pk,
            "name": registration.name,
            "client_id": registration.client_id,
            "deployment_id": registration.deployment_id,
            "issuer": registration.issuer,
            "oidc_init_url": registration.oidc_init_url,
            "target_link_uri": registration.target_link_uri,
            "launch_url": registration.launch_url,
        },
        "saved_app_instance": {
            "pk": launch.pk if launch else None,
            "target_link_uri": launch.target_link_uri if launch else launch_state.target_link_uri,
            "context_id": launch.context_id if launch else launch_state.context_id,
            "context_label": launch.context_label if launch else launch_state.context_label,
            "context_title": launch.context_title if launch else launch_state.context_title,
        },
    }


def _oidc_debug_response(request, error_message, *, status=400, launch_state=None, jwt_payload=None, id_token=""):
    traceback_text = traceback.format_exc()
    if traceback_text.strip() == "NoneType: None":
        traceback_text = ""
    context = {
        "error_message": error_message,
        "request_payload_json": _pretty_json(_request_payload(request)),
        "launch_state_json": _pretty_json(_launch_state_payload(launch_state)) if launch_state else "",
        "jwt_payload_json": _pretty_json(jwt_payload) if jwt_payload else "",
        "id_token": id_token,
        "traceback": traceback_text,
    }
    return render(request, "launch/oidc_debug.html", context, status=status)


def _example_context_values():
    course_number = random.randint(100, 999)
    prefix = f"cs-{course_number}-year"
    return {
        "context_id": f"{prefix}-id",
        "context_label": f"{prefix}-label",
        "context_title": f"{prefix}-title",
    }


def _launch_form_context(
    request,
    registration,
    *,
    latest_launch=None,
    target_link_uri="",
    context_id="",
    context_label="",
    context_title="",
    error_message="",
):
    examples = _example_context_values()
    return {
        "registration": registration,
        "target_link_uri": target_link_uri or request.GET.get("target_link_uri", "") or (latest_launch.target_link_uri if latest_launch and latest_launch.target_link_uri else registration.target_link_uri),
        "context_id": context_id or request.GET.get("context_id", "") or (latest_launch.context_id if latest_launch else "") or examples["context_id"],
        "context_label": context_label or request.GET.get("context_label", "") or (latest_launch.context_label if latest_launch else "") or examples["context_label"],
        "context_title": context_title or request.GET.get("context_title", "") or (latest_launch.context_title if latest_launch else "") or examples["context_title"],
        "error_message": error_message,
        "config_fields": [
            ("title", registration.name),
            ("target_link_uri", registration.target_link_uri),
            ("oidc_initiation_url", registration.oidc_init_url),
            ("public_jwk_url", registration.tool_jwks_url),
        ],
    }



@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    launches = Launch.objects.select_related("registration").order_by("-updated_at", "-pk")
    return render(
        request,
        "launch/tool_list.html",
        {"registrations": registrations, "launches": launches},
    )


@login_required
@require_POST
def delete_registration(request, registration_id):
    registration = get_object_or_404(LTIToolRegistration, id=registration_id)
    registration.delete()
    return redirect("tool_list")


@login_required
@require_POST
def delete_launch(request, launch_id):
    launch = get_object_or_404(Launch, id=launch_id)
    launch.delete()
    return redirect("tool_list")


@login_required
def launch_oidc_init(request, launch_id):
    launch = get_object_or_404(
        Launch.objects.select_related("registration"),
        id=launch_id,
    )
    registration = launch.registration
    launch_state = LTILaunchState.objects.create(
        user=request.user,
        registration=registration,
        launch=launch,
        target_link_uri=launch.target_link_uri or registration.target_link_uri,
        context_id=launch.context_id,
        context_label=launch.context_label,
        context_title=launch.context_title,
    )
    oidc_init_payload = {
        "iss": registration.issuer,
        "login_hint": launch_state.state,
        "lti_message_hint": launch_state.state,
        "target_link_uri": launch_state.target_link_uri,
        "context_id": launch_state.context_id,
        "context_label": launch_state.context_label,
        "context_title": launch_state.context_title,
        "client_id": registration.client_id,
    }
    return render(
        request,
        "launch/launch_init_submit.html",
        {
            **oidc_init_payload,
            "post_url": registration.oidc_init_url,
            "oidc_init_payload_json": json.dumps(
                oidc_init_payload,
                indent=2,
                sort_keys=True,
            ),
        },
    )


@login_required
def launch_init(request, registration_id):
    registration = get_object_or_404(LTIToolRegistration, id=registration_id)
    selected_launch = None
    launch_pk = request.GET.get("launch")
    if launch_pk:
        selected_launch = get_object_or_404(Launch, pk=launch_pk, registration=registration)
    latest_launch = selected_launch
    if request.method == "POST":
        target_link_uri = request.POST.get("target_link_uri", "").strip() or registration.target_link_uri
        context_id = request.POST.get("context_id", "").strip()
        context_label = request.POST.get("context_label", "").strip()
        context_title = request.POST.get("context_title", "").strip()
        launch = (
            Launch.objects.filter(
                registration__client_id=registration.client_id,
                context_id=context_id,
            )
            .order_by("-updated_at", "-pk")
            .first()
        )
        if launch is None:
            launch = Launch(registration=registration, context_id=context_id)
        launch.registration = registration
        launch.target_link_uri = target_link_uri or None
        launch.context_label = context_label
        launch.context_title = context_title
        launch.save()
        return redirect("tool_list")

    context = _launch_form_context(request, registration, latest_launch=latest_launch)
    return render(request, "launch/launch_init.html", context)


def auth_callback(request):
    login_hint = request.GET.get("login_hint", "")
    client_id = request.GET.get("client_id", "")
    tool_nonce = request.GET.get("nonce", "")
    tool_state = request.GET.get("state", "")
    redirect_uri = request.GET.get("redirect_uri", "")


    try:
        launch_state = LTILaunchState.objects.get(state=login_hint)
    except LTILaunchState.DoesNotExist:
        return _oidc_debug_response(
            request,
            f"Unknown or already-used login_hint: {login_hint!r}",
        )

    if launch_state.is_expired():
        error_message = "Launch state has expired."
        launch_state.delete()
        return _oidc_debug_response(request, error_message, launch_state=launch_state)

    if launch_state.registration.client_id != client_id:
        return _oidc_debug_response(
            request,
            "client_id does not match the launch state's registration.",
            launch_state=launch_state,
        )

    launch_obj = launch_state.launch
    launch_target_link_uri = launch_obj.target_link_uri if launch_obj and launch_obj.target_link_uri else launch_state.target_link_uri
    launch_context = {
        "id": launch_obj.context_id if launch_obj else launch_state.context_id,
        "label": launch_obj.context_label if launch_obj else launch_state.context_label,
        "title": launch_obj.context_title if launch_obj else launch_state.context_title,
    }

    jwt_payload = build_claims(
        launch_state.user,
        launch_state.registration,
        tool_nonce,
        target_link_uri=launch_target_link_uri,
        context=launch_context,
    )
    id_token = sign_claims(jwt_payload)
    target_url = redirect_uri or launch_state.registration.launch_url
    launch_state_json = _pretty_json(_launch_state_payload(launch_state))
    launch_state.delete()
    context = {
        "launch_url": target_url,
        "id_token": id_token,
        "state": tool_state,
        "request_payload_json": _pretty_json(_request_payload(request)),
        "launch_state_json": launch_state_json,
        "jwt_payload_json": _pretty_json(jwt_payload),
    }
    logger.info("AUTH_CALLBACK CONTEXT = %s", context)
    return render(request, "launch/auth_callback.html", context)
