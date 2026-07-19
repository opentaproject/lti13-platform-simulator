from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from launch import views as launch_views
from platform_config import views as platform_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("jwks.json", platform_views.jwks, name="jwks"),
    path("configure-by-url/", platform_views.configure_by_url, name="configure_by_url"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", launch_views.tool_list, name="tool_list"),
    path("launch/<int:registration_id>/init/", launch_views.launch_init, name="launch_init"),
    path("api/lti/authorize_redirect", launch_views.auth_callback, name="auth_callback"),
]
