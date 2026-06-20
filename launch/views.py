from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from platform_config.models import LTIToolRegistration


@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})
