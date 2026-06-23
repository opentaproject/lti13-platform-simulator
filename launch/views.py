from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseBadRequest

from platform_config.models import LTIToolRegistration
from .models import LTILaunchState
from .jwt_utils import sign_launch_jwt
import logging
logger = logging.getLogger(__name__)



@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})


@login_required
def launch_init(request, registration_id):
    registration = get_object_or_404(LTIToolRegistration, id=registration_id)
    launch_state = LTILaunchState.objects.create(user=request.user, registration=registration)
    context = {
        "registration": registration,
        "login_hint": launch_state.state,
        "login_hint_clear": f"user={request.user.username} registration={registration.name}",
    }
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

    id_token = sign_launch_jwt(launch_state.user, launch_state.registration, tool_nonce)
    target_url = redirect_uri or launch_state.registration.launch_url
    launch_state.delete()
    context = {"launch_url": target_url, "id_token": id_token, "state": tool_state}
    logger.error(f"AUTH_CALLBACK CONTEXT = {context}")
    return render(request, "launch/auth_callback.html", context)
