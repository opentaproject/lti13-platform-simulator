from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from platform_config.models import LTIToolRegistration


@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})


@login_required
def launch_init(request, registration_id):
    return HttpResponse("Not implemented yet")
