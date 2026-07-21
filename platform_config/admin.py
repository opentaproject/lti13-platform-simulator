from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse

from .forms import ToolRegistrationImportForm
from .models import LTIPlatformKey, LTIToolRegistration
from .views import load_tool_config, registration_kwargs_from_config


@admin.register(LTIPlatformKey)
class LTIPlatformKeyAdmin(admin.ModelAdmin):
    list_display = ("kid", "created_at")
    readonly_fields = ("kid", "private_key_pem", "public_key_pem", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LTIToolRegistration)
class LTIToolRegistrationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "client_id", "issuer", "deployment_id")
    change_list_template = "admin/platform_config/ltitoolregistration/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "configure-by-url/",
                self.admin_site.admin_view(self.configure_by_url_view),
                name="platform_config_ltitoolregistration_configure_by_url",
            ),
        ]
        return custom_urls + urls

    def configure_by_url_view(self, request):
        if request.method == "POST":
            form = ToolRegistrationImportForm(request.POST)
            if form.is_valid():
                try:
                    config = load_tool_config(form.cleaned_data["config_url"])
                    issuer = (
                        form.cleaned_data["issuer"].strip()
                        if form.cleaned_data["issuer"]
                        else request.build_absolute_uri("/").rstrip("/")
                    )
                    registration = LTIToolRegistration.objects.create(
                        **registration_kwargs_from_config(
                            config,
                            client_id=form.cleaned_data["client_id"].strip(),
                            deployment_id=form.cleaned_data["deployment_id"].strip(),
                            issuer=issuer,
                            resource_link_id=form.cleaned_data["resource_link_id"].strip(),
                        )
                    )
                except ValidationError as exc:
                    form.add_error(None, exc.message)
                except Exception as exc:
                    form.add_error(None, f"Could not import config: {exc}")
                else:
                    self.message_user(
                        request,
                        f'Imported tool registration "{registration.name}" from URL.',
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse(
                            "admin:platform_config_ltitoolregistration_change",
                            args=[registration.pk],
                        )
                    )
        else:
            form = ToolRegistrationImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Configure LTI tool by URL",
            "form": form,
        }
        return render(
            request,
            "admin/platform_config/ltitoolregistration/configure_by_url.html",
            context,
        )
