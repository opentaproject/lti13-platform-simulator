from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404

from platform_config.models import LTIToolRegistration
from .models import LTILaunchState


@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})


@login_required
def launch_init(request, registration_id):
    registration = get_object_or_404(LTIToolRegistration, id=registration_id)
    launch_state = LTILaunchState.objects.create(user=request.user, registration=registration)
    context = {"registration": registration, "login_hint": launch_state.state}
    return render(request, "launch/launch_init.html", context)
