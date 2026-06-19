from django.contrib import admin

from .models import LTIPlatformKey


@admin.register(LTIPlatformKey)
class LTIPlatformKeyAdmin(admin.ModelAdmin):
    list_display = ("kid", "created_at")
    readonly_fields = ("kid", "private_key_pem", "public_key_pem", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
