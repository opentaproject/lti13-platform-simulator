from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Launch, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(Launch)
class LaunchAdmin(admin.ModelAdmin):
    list_display = (
        "target_link_uri",
        "registration",
        "context_id",
        "context_label",
        "updated_at",
    )
    search_fields = (
        "target_link_uri",
        "context_id",
        "context_label",
        "context_title",
        "registration__name",
    )
    list_filter = ("registration", "created_at", "updated_at")
