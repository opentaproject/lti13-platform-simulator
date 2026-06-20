from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from platform_config.models import LTIToolRegistration


@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})


def launch_init(request, registration_id):
    # Stub view for Task 9
    return HttpResponse("Launch init - to be implemented in Task 9")
