from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseBadRequest

from platform_config.models import LTIToolRegistration
from .models import Launch, LTILaunchState
from .jwt_utils import sign_launch_jwt
import logging
logger = logging.getLogger(__name__)


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
    return {
        "registration": registration,
        "target_link_uri": target_link_uri or request.GET.get("target_link_uri", "") or (latest_launch.target_link_uri if latest_launch and latest_launch.target_link_uri else registration.target_link_uri),
        "context_id": context_id or request.GET.get("context_id", "") or (latest_launch.context_id if latest_launch else ""),
        "context_label": context_label or request.GET.get("context_label", "") or (latest_launch.context_label if latest_launch else ""),
        "context_title": context_title or request.GET.get("context_title", "") or (latest_launch.context_title if latest_launch else ""),
        "error_message": error_message,
    }



@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})


@login_required
def launch_init(request, registration_id):
    registration = get_object_or_404(LTIToolRegistration, id=registration_id)
    latest_launch = Launch.objects.filter(registration=registration).order_by("-updated_at", "-pk").first()
    if request.method == "POST":
        target_link_uri = request.POST.get("target_link_uri", "").strip() or registration.target_link_uri
        context_id = request.POST.get("context_id", "").strip()
        context_label = request.POST.get("context_label", "").strip()
        context_title = request.POST.get("context_title", "").strip()
        existing_target = Launch.objects.filter(target_link_uri=target_link_uri).first() if target_link_uri else None
        if existing_target and existing_target.context_id and context_id and existing_target.context_id != context_id:
            context = _launch_form_context(
                request,
                registration,
                latest_launch=latest_launch,
                target_link_uri=target_link_uri,
                context_id=context_id,
                context_label=context_label,
                context_title=context_title,
                error_message=(
                    f"Collision: target_link_uri {target_link_uri} is already bound to "
                    f"context_id {existing_target.context_id}."
                ),
            )
            return render(request, "launch/launch_init.html", context, status=400)
        existing_context = (
            Launch.objects.filter(context_id=context_id).exclude(target_link_uri=target_link_uri).first()
            if context_id
            else None
        )
        if existing_context and existing_context.target_link_uri:
            context = _launch_form_context(
                request,
                registration,
                latest_launch=latest_launch,
                target_link_uri=target_link_uri,
                context_id=context_id,
                context_label=context_label,
                context_title=context_title,
                error_message=(
                    f"Collision: context_id {context_id} is already bound to "
                    f"target_link_uri {existing_context.target_link_uri}."
                ),
            )
            return render(request, "launch/launch_init.html", context, status=400)
        launch_lookup = {"target_link_uri": target_link_uri or None}
        launch_defaults = {
            "registration": registration,
            "context_id": context_id,
            "context_label": context_label,
            "context_title": context_title,
        }
        launch_obj, _ = Launch.objects.update_or_create(defaults=launch_defaults, **launch_lookup)
        launch_state = LTILaunchState.objects.create(
            user=request.user,
            registration=registration,
            launch=launch_obj,
            target_link_uri=target_link_uri,
            context_id=context_id,
            context_label=context_label,
            context_title=context_title,
        )
        context = {
            "registration": registration,
            "iss": registration.issuer,
            "login_hint": launch_state.state,
            "login_hint_clear": f"user={request.user.username} registration={registration.name}",
            "lti_message_hint": launch_state.state,
            "target_link_uri": target_link_uri,
            "context_id": context_id,
            "context_label": context_label,
            "context_title": context_title,
            "post_url": registration.oidc_init_url,
            "client_id": registration.client_id,
            "auto_submit": True,
        }
        return render(request, "launch/launch_init_submit.html", context)

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
        return HttpResponseBadRequest("Unknown or already-used login_hint.")

    if launch_state.is_expired():
        launch_state.delete()
        return HttpResponseBadRequest("Launch state has expired.")

    if launch_state.registration.client_id != client_id:
        return HttpResponseBadRequest(
            "client_id does not match the launch state's registration."
        )

    launch_obj = launch_state.launch
    launch_target_link_uri = launch_obj.target_link_uri if launch_obj and launch_obj.target_link_uri else launch_state.target_link_uri
    launch_context = {
        "id": launch_obj.context_id if launch_obj else launch_state.context_id,
        "label": launch_obj.context_label if launch_obj else launch_state.context_label,
        "title": launch_obj.context_title if launch_obj else launch_state.context_title,
    }

    id_token = sign_launch_jwt(
        launch_state.user,
        launch_state.registration,
        tool_nonce,
        target_link_uri=launch_target_link_uri,
        context=launch_context,
    )
    target_url = redirect_uri or launch_state.registration.launch_url
    launch_state.delete()
    context = {"launch_url": target_url, "id_token": id_token, "state": tool_state}
    logger.error(f"AUTH_CALLBACK CONTEXT = {context}")
    return render(request, "launch/auth_callback.html", context)
