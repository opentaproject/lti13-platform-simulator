# LTI 1.3 Platform Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Django app that simulates a Canvas-like LTI 1.3 platform — login initiation, OIDC auth callback that signs an LTI JWT, and a JWKS endpoint — so the OpenTA2 tool can be launch-tested without real Canvas.

**Architecture:** Django project `simulator` with two apps: `platform_config` (signing key, tool registrations, JWKS endpoint, admin) and `launch` (user profile/role, launch state tracking, tool list, launch-init view, auth callback, JWT signing). One global RSA platform key, DB-backed launch state (not session) to survive the cross-domain redirect.

**Tech Stack:** Django (latest 5.x), SQLite, PyJWT, cryptography, plain HTML templates, Django's built-in auth views for login/logout.

Reference spec: `docs/superpowers/specs/2026-06-19-lti13-platform-simulator-design.md`

---

### Task 1: Environment & Django Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `manage.py`, `simulator/settings.py`, `simulator/urls.py`, `simulator/wsgi.py`, `simulator/asgi.py`, `simulator/__init__.py` (via `django-admin startproject`)
- Create: `platform_config/` app skeleton (via `startapp`)
- Create: `launch/` app skeleton (via `startapp`)
- Modify: `simulator/settings.py`

- [ ] **Step 1: Create a virtualenv and requirements.txt**

```bash
cd /Users/ostlund/WWW/canvas-demo
python3 -m venv .venv
source .venv/bin/activate
```

Create `requirements.txt`:

```
Django>=5.0,<6.0
PyJWT>=2.8,<3.0
cryptography>=42.0
```

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Scaffold the Django project and apps**

```bash
django-admin startproject simulator .
python manage.py startapp platform_config
python manage.py startapp launch
```

- [ ] **Step 3: Register apps and configure auth/login settings**

In `simulator/settings.py`, find `INSTALLED_APPS` and add the two new apps:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "platform_config",
    "launch",
]
```

At the end of `simulator/settings.py`, add:

```python
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "tool_list"
LOGOUT_REDIRECT_URL = "login"
```

- [ ] **Step 4: Verify the project boots**

```bash
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt manage.py simulator platform_config launch .gitignore
git commit -m "Scaffold Django project with platform_config and launch apps"
```

---

### Task 2: Auth Pages (Login/Logout)

**Files:**
- Create: `simulator/urls.py` (modify — add login/logout routes)
- Create: `launch/templates/registration/login.html`

- [ ] **Step 1: Add login/logout URLs**

Replace the contents of `simulator/urls.py` with:

```python
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
]
```

(More routes are added to this file in later tasks.)

- [ ] **Step 2: Create the login template**

Create directory `launch/templates/registration/` and create `launch/templates/registration/login.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Log in</title></head>
<body>
  <h1>LTI Platform Simulator — Log in</h1>
  <form method="post">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit">Log in</button>
  </form>
</body>
</html>
```

- [ ] **Step 3: Run migrations and create a test user, then verify the login page renders**

```bash
python manage.py migrate
python manage.py createsuperuser --username admin --email admin@example.org
python manage.py runserver &
sleep 1
curl -s http://127.0.0.1:8000/login/ | grep -i "Log in"
kill %1
```

Expected: output includes `Log in` (the page heading/button), confirming the template rendered without error.

- [ ] **Step 4: Commit**

```bash
git add simulator/urls.py launch/templates
git commit -m "Add login/logout routes and login template"
```

---

### Task 3: UserProfile Model, Signal, and Admin

**Files:**
- Modify: `launch/models.py`
- Modify: `launch/apps.py`
- Create: `launch/signals.py`
- Modify: `launch/admin.py`
- Create: `launch/migrations/0001_initial.py` (via makemigrations)
- Test: `launch/tests.py`

- [ ] **Step 1: Write the model**

In `launch/models.py`:

```python
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    INSTRUCTOR = "instructor"
    STUDENT = "student"
    ROLE_CHOICES = [(INSTRUCTOR, "Instructor"), (STUDENT, "Student")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=STUDENT)

    def __str__(self):
        return f"{self.user.username} ({self.role})"
```

- [ ] **Step 2: Write the signal that auto-creates a profile for new users**

Create `launch/signals.py`:

```python
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
```

Wire it up in `launch/apps.py`:

```python
from django.apps import AppConfig


class LaunchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "launch"

    def ready(self):
        from . import signals  # noqa: F401
```

- [ ] **Step 3: Write the failing test**

In `launch/tests.py`:

```python
from django.contrib.auth.models import User
from django.test import TestCase

from .models import UserProfile


class UserProfileSignalTests(TestCase):
    def test_creating_a_user_creates_a_profile(self):
        user = User.objects.create_user(username="alice", password="pw12345")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.role, UserProfile.STUDENT)
```

- [ ] **Step 4: Make and run migrations, then run the test**

```bash
python manage.py makemigrations launch
python manage.py migrate
python manage.py test launch.tests.UserProfileSignalTests -v 2
```

Expected: `OK` (1 test passed).

- [ ] **Step 5: Wire up the admin**

In `launch/admin.py`:

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
```

- [ ] **Step 6: Commit**

```bash
git add launch/models.py launch/signals.py launch/apps.py launch/admin.py launch/migrations launch/tests.py
git commit -m "Add UserProfile model with auto-create signal and admin inline"
```

---

### Task 4: LTIPlatformKey Model and Key/JWK Helpers

**Files:**
- Modify: `platform_config/models.py`
- Create: `platform_config/keys.py`
- Modify: `platform_config/admin.py`
- Create: `platform_config/migrations/0001_initial.py` (via makemigrations)
- Test: `platform_config/tests.py`

- [ ] **Step 1: Write the model**

In `platform_config/models.py`:

```python
from django.db import models


class LTIPlatformKey(models.Model):
    kid = models.CharField(max_length=255, unique=True)
    private_key_pem = models.TextField()
    public_key_pem = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.kid
```

- [ ] **Step 2: Make and run migrations**

```bash
python manage.py makemigrations platform_config
python manage.py migrate
```

- [ ] **Step 3: Write the failing tests for key generation and JWK export**

In `platform_config/tests.py`:

```python
import base64

from cryptography.hazmat.primitives import serialization
from django.test import TestCase

from .keys import generate_keypair, get_or_create_platform_key, public_key_to_jwk
from .models import LTIPlatformKey


def b64url_to_int(value):
    padded = value + "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


class KeyGenerationTests(TestCase):
    def test_generate_keypair_produces_matching_private_and_public_key(self):
        private_pem, public_pem = generate_keypair()
        private_key = serialization.load_pem_private_key(
            private_pem.encode("utf-8"), password=None
        )
        public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
        self.assertEqual(private_key.key_size, 2048)
        self.assertEqual(
            private_key.public_key().public_numbers(), public_key.public_numbers()
        )

    def test_get_or_create_platform_key_creates_only_once(self):
        self.assertEqual(LTIPlatformKey.objects.count(), 0)
        key_one = get_or_create_platform_key()
        key_two = get_or_create_platform_key()
        self.assertEqual(key_one.id, key_two.id)
        self.assertEqual(LTIPlatformKey.objects.count(), 1)

    def test_public_key_to_jwk_round_trip(self):
        key = get_or_create_platform_key()
        jwk = public_key_to_jwk(key)
        public_key = serialization.load_pem_public_key(
            key.public_key_pem.encode("utf-8")
        )
        numbers = public_key.public_numbers()

        self.assertEqual(b64url_to_int(jwk["n"]), numbers.n)
        self.assertEqual(b64url_to_int(jwk["e"]), numbers.e)
        self.assertEqual(jwk["kid"], key.kid)
        self.assertEqual(jwk["kty"], "RSA")
        self.assertEqual(jwk["alg"], "RS256")
```

- [ ] **Step 4: Run the tests to verify they fail**

```bash
python manage.py test platform_config.tests.KeyGenerationTests -v 2
```

Expected: `ModuleNotFoundError` or `ImportError` for `platform_config.keys` (module doesn't exist yet).

- [ ] **Step 5: Implement `platform_config/keys.py`**

```python
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .models import LTIPlatformKey

DEFAULT_KID = "platform-key-1"


def generate_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def get_or_create_platform_key():
    key = LTIPlatformKey.objects.first()
    if key is not None:
        return key
    private_pem, public_pem = generate_keypair()
    return LTIPlatformKey.objects.create(
        kid=DEFAULT_KID, private_key_pem=private_pem, public_key_pem=public_pem
    )


def _int_to_base64url(value):
    byte_length = (value.bit_length() + 7) // 8
    value_bytes = value.to_bytes(byte_length, "big")
    return base64.urlsafe_b64encode(value_bytes).rstrip(b"=").decode("ascii")


def public_key_to_jwk(platform_key):
    public_key = serialization.load_pem_public_key(
        platform_key.public_key_pem.encode("utf-8")
    )
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": platform_key.kid,
        "n": _int_to_base64url(numbers.n),
        "e": _int_to_base64url(numbers.e),
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python manage.py test platform_config.tests.KeyGenerationTests -v 2
```

Expected: `OK` (3 tests passed).

- [ ] **Step 7: Lock down the key in admin (read-only, no add/delete)**

In `platform_config/admin.py`:

```python
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
```

- [ ] **Step 8: Commit**

```bash
git add platform_config/models.py platform_config/keys.py platform_config/admin.py platform_config/migrations platform_config/tests.py
git commit -m "Add LTIPlatformKey model with RSA keypair generation and JWK export"
```

---

### Task 5: JWKS Endpoint

**Files:**
- Modify: `platform_config/views.py`
- Modify: `simulator/urls.py`
- Test: `platform_config/tests.py`

- [ ] **Step 1: Write the failing test**

Append to `platform_config/tests.py`:

```python
from django.test import TestCase


class JwksViewTests(TestCase):
    def test_jwks_endpoint_returns_one_rsa_key(self):
        response = self.client.get("/jwks.json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["keys"]), 1)
        self.assertEqual(data["keys"][0]["kty"], "RSA")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python manage.py test platform_config.tests.JwksViewTests -v 2
```

Expected: `404` (route doesn't exist yet) causing assertion failure on status code.

- [ ] **Step 3: Implement the view**

In `platform_config/views.py`:

```python
from django.http import JsonResponse

from .keys import get_or_create_platform_key, public_key_to_jwk


def jwks(request):
    platform_key = get_or_create_platform_key()
    return JsonResponse({"keys": [public_key_to_jwk(platform_key)]})
```

- [ ] **Step 4: Wire up the URL**

In `simulator/urls.py`, add the import and route:

```python
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from platform_config import views as platform_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("jwks.json", platform_views.jwks, name="jwks"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
]
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
python manage.py test platform_config.tests.JwksViewTests -v 2
```

Expected: `OK` (1 test passed).

- [ ] **Step 6: Commit**

```bash
git add platform_config/views.py simulator/urls.py platform_config/tests.py
git commit -m "Add /jwks.json endpoint"
```

---

### Task 6: LTIToolRegistration Model and Admin

**Files:**
- Modify: `platform_config/models.py`
- Modify: `platform_config/admin.py`
- Create: `platform_config/migrations/0002_ltitoolregistration.py` (via makemigrations)

- [ ] **Step 1: Add the model**

Append to `platform_config/models.py`:

```python
class LTIToolRegistration(models.Model):
    name = models.CharField(max_length=255)
    client_id = models.CharField(max_length=255)
    oidc_init_url = models.URLField()
    launch_url = models.URLField()
    tool_jwks_url = models.URLField()
    target_link_uri = models.URLField()
    deployment_id = models.CharField(max_length=255)
    issuer = models.CharField(max_length=255)
    context_id = models.CharField(max_length=255)
    context_label = models.CharField(max_length=255)
    context_title = models.CharField(max_length=255)
    resource_link_id = models.CharField(max_length=255)

    def __str__(self):
        return self.name
```

- [ ] **Step 2: Make and run migrations**

```bash
python manage.py makemigrations platform_config
python manage.py migrate
```

- [ ] **Step 3: Register in admin**

Append to `platform_config/admin.py`:

```python
from .models import LTIToolRegistration  # add to existing import line


@admin.register(LTIToolRegistration)
class LTIToolRegistrationAdmin(admin.ModelAdmin):
    list_display = ("name", "client_id", "issuer", "deployment_id")
```

(Merge the `from .models import ...` line with the existing `LTIPlatformKey` import rather than duplicating it — final import line should read `from .models import LTIPlatformKey, LTIToolRegistration`.)

- [ ] **Step 4: Verify via the admin shell**

```bash
python manage.py shell -c "
from platform_config.models import LTIToolRegistration
LTIToolRegistration.objects.create(
    name='OpenTA2', client_id='client-123',
    oidc_init_url='https://lti13.openta-demo.org/oidc/init',
    launch_url='https://lti13.openta-demo.org/launch',
    tool_jwks_url='https://lti13.openta-demo.org/.well-known/jwks.json',
    target_link_uri='https://lti13.openta-demo.org/launch',
    deployment_id='deploy-1', issuer='https://simulator.example.org',
    context_id='course-1', context_label='FFM516', context_title='Exam Grading Course',
    resource_link_id='resource-1',
)
print(LTIToolRegistration.objects.count())
"
```

Expected: prints `1`.

- [ ] **Step 5: Commit**

```bash
git add platform_config/models.py platform_config/admin.py platform_config/migrations
git commit -m "Add LTIToolRegistration model and admin"
```

---

### Task 7: LTILaunchState Model

**Files:**
- Modify: `launch/models.py`
- Create: `launch/migrations/0002_ltilaunchstate.py` (via makemigrations)
- Test: `launch/tests.py`

- [ ] **Step 1: Write the failing test**

Append to `launch/tests.py`:

```python
from datetime import timedelta

from django.utils import timezone

from platform_config.models import LTIToolRegistration

from .models import LTILaunchState


def make_registration(**overrides):
    defaults = dict(
        name="OpenTA2",
        client_id="client-123",
        oidc_init_url="https://lti13.openta-demo.org/oidc/init",
        launch_url="https://lti13.openta-demo.org/launch",
        tool_jwks_url="https://lti13.openta-demo.org/.well-known/jwks.json",
        target_link_uri="https://lti13.openta-demo.org/launch",
        deployment_id="deploy-1",
        issuer="https://simulator.example.org",
        context_id="course-1",
        context_label="FFM516",
        context_title="Exam Grading Course",
        resource_link_id="resource-1",
    )
    defaults.update(overrides)
    return LTIToolRegistration.objects.create(**defaults)


class LTILaunchStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="pw12345")
        self.registration = make_registration()

    def test_state_and_nonce_are_auto_generated_and_unique(self):
        state_one = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        state_two = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        self.assertTrue(state_one.state)
        self.assertTrue(state_one.nonce)
        self.assertNotEqual(state_one.state, state_two.state)

    def test_is_expired_false_when_fresh(self):
        state = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        self.assertFalse(state.is_expired())

    def test_is_expired_true_after_ttl(self):
        state = LTILaunchState.objects.create(user=self.user, registration=self.registration)
        state.created_at = timezone.now() - timedelta(minutes=10)
        state.save(update_fields=["created_at"])
        self.assertTrue(state.is_expired())
```

Add the needed imports at the top of `launch/tests.py` (merge with existing `from django.test import TestCase` / `from django.contrib.auth.models import User` lines if already present).

- [ ] **Step 2: Run the test to verify it fails**

```bash
python manage.py test launch.tests.LTILaunchStateTests -v 2
```

Expected: `ImportError: cannot import name 'LTILaunchState'`.

- [ ] **Step 3: Implement the model**

Append to `launch/models.py`:

```python
import secrets
from datetime import timedelta

from django.utils import timezone

from platform_config.models import LTIToolRegistration

LAUNCH_STATE_TTL = timedelta(minutes=5)


def generate_token():
    return secrets.token_urlsafe(32)


class LTILaunchState(models.Model):
    state = models.CharField(max_length=255, unique=True, default=generate_token)
    nonce = models.CharField(max_length=255, default=generate_token)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    registration = models.ForeignKey(LTIToolRegistration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() - self.created_at > LAUNCH_STATE_TTL
```

- [ ] **Step 4: Make and run migrations, then run the test**

```bash
python manage.py makemigrations launch
python manage.py migrate
python manage.py test launch.tests.LTILaunchStateTests -v 2
```

Expected: `OK` (3 tests passed).

- [ ] **Step 5: Commit**

```bash
git add launch/models.py launch/migrations launch/tests.py
git commit -m "Add LTILaunchState model with TTL-based expiry"
```

---

### Task 8: Tool List View and Template

**Files:**
- Modify: `launch/views.py`
- Modify: `simulator/urls.py`
- Create: `launch/templates/launch/tool_list.html`
- Test: `launch/tests.py`

- [ ] **Step 1: Write the failing test**

Append to `launch/tests.py`:

```python
class ToolListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carol", password="pw12345")
        self.registration = make_registration()

    def test_requires_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_lists_registrations_when_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.registration.name)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python manage.py test launch.tests.ToolListViewTests -v 2
```

Expected: `404` for `/` (no route yet).

- [ ] **Step 3: Implement the view**

In `launch/views.py`:

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from platform_config.models import LTIToolRegistration


@login_required
def tool_list(request):
    registrations = LTIToolRegistration.objects.all()
    return render(request, "launch/tool_list.html", {"registrations": registrations})
```

- [ ] **Step 4: Create the template**

Create `launch/templates/launch/tool_list.html`:

```html
<!DOCTYPE html>
<html>
<head><title>LTI Tools</title></head>
<body>
  <h1>Available LTI Tools</h1>
  <p>
    Logged in as {{ user.username }} ({{ user.profile.role }}) —
    <a href="{% url 'logout' %}">Log out</a>
  </p>
  <ul>
    {% for registration in registrations %}
      <li><a href="{% url 'launch_init' registration.id %}">{{ registration.name }}</a></li>
    {% endfor %}
  </ul>
</body>
</html>
```

- [ ] **Step 5: Wire up the URL**

In `simulator/urls.py`, add the import and route:

```python
from launch import views as launch_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("jwks.json", platform_views.jwks, name="jwks"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", launch_views.tool_list, name="tool_list"),
]
```

(`launch_init` route is added in Task 9 — the `{% url 'launch_init' ... %}` template tag will fail until then, which is expected; the test in this task doesn't click the link.)

- [ ] **Step 6: Run the test to verify it passes**

```bash
python manage.py test launch.tests.ToolListViewTests -v 2
```

Expected: `OK` (2 tests passed).

- [ ] **Step 7: Commit**

```bash
git add launch/views.py launch/templates/launch/tool_list.html simulator/urls.py launch/tests.py
git commit -m "Add tool list view"
```

---

### Task 9: Launch-Init View and Template

**Files:**
- Modify: `launch/views.py`
- Modify: `simulator/urls.py`
- Create: `launch/templates/launch/launch_init.html`
- Test: `launch/tests.py`

- [ ] **Step 1: Write the failing test**

Append to `launch/tests.py`:

```python
from .models import LTILaunchState


class LaunchInitViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dave", password="pw12345")
        self.registration = make_registration()

    def test_creates_launch_state_and_renders_auto_submit_form(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/launch/{self.registration.id}/init/")
        self.assertEqual(response.status_code, 200)

        launch_state = LTILaunchState.objects.get(user=self.user, registration=self.registration)
        self.assertContains(response, self.registration.oidc_init_url)
        self.assertContains(response, launch_state.state)
        self.assertContains(response, self.registration.client_id)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python manage.py test launch.tests.LaunchInitViewTests -v 2
```

Expected: `404` (no route yet).

- [ ] **Step 3: Implement the view**

Append to `launch/views.py`:

```python
from django.shortcuts import get_object_or_404

from .models import LTILaunchState


@login_required
def launch_init(request, registration_id):
    registration = get_object_or_404(LTIToolRegistration, id=registration_id)
    launch_state = LTILaunchState.objects.create(user=request.user, registration=registration)
    context = {"registration": registration, "login_hint": launch_state.state}
    return render(request, "launch/launch_init.html", context)
```

- [ ] **Step 4: Create the template**

Create `launch/templates/launch/launch_init.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Launching {{ registration.name }}</title></head>
<body onload="document.forms[0].submit()">
  <p>Launching {{ registration.name }}...</p>
  <form method="post" action="{{ registration.oidc_init_url }}">
    <input type="hidden" name="iss" value="{{ registration.issuer }}">
    <input type="hidden" name="login_hint" value="{{ login_hint }}">
    <input type="hidden" name="lti_message_hint" value="{{ login_hint }}">
    <input type="hidden" name="target_link_uri" value="{{ registration.target_link_uri }}">
    <input type="hidden" name="client_id" value="{{ registration.client_id }}">
    <button type="submit">Continue</button>
  </form>
</body>
</html>
```

- [ ] **Step 5: Wire up the URL**

In `simulator/urls.py`, add the route:

```python
    path("launch/<int:registration_id>/init/", launch_views.launch_init, name="launch_init"),
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
python manage.py test launch.tests.LaunchInitViewTests -v 2
```

Expected: `OK` (1 test passed).

- [ ] **Step 7: Also re-run the Task 8 tool list tests, since they reference `launch_init` in the template**

```bash
python manage.py test launch.tests.ToolListViewTests -v 2
```

Expected: `OK` (2 tests passed).

- [ ] **Step 8: Commit**

```bash
git add launch/views.py launch/templates/launch/launch_init.html simulator/urls.py launch/tests.py
git commit -m "Add launch-init view that posts login initiation to the tool's oidc/init"
```

---

### Task 10: JWT Claim Builder and Signer

**Files:**
- Create: `launch/jwt_utils.py`
- Test: `launch/tests.py`

> Module is named `jwt_utils.py`, not `jwt.py`, to avoid any ambiguity with the third-party `jwt` (PyJWT) package.

- [ ] **Step 1: Write the failing tests**

Append to `launch/tests.py`:

```python
import jwt as pyjwt
from cryptography.hazmat.primitives import serialization

from platform_config.keys import get_or_create_platform_key

from .jwt_utils import build_claims, sign_launch_jwt
from .models import UserProfile


class JwtClaimTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="instructor1",
            email="instructor1@example.org",
            first_name="Ines",
            last_name="Tructor",
        )
        self.user.profile.role = UserProfile.INSTRUCTOR
        self.user.profile.save()
        self.registration = make_registration()

    def test_build_claims_contains_required_fields(self):
        claims = build_claims(self.user, self.registration, tool_nonce="tool-nonce-1")
        self.assertEqual(claims["iss"], self.registration.issuer)
        self.assertEqual(claims["sub"], str(self.user.id))
        self.assertEqual(claims["aud"], self.registration.client_id)
        self.assertEqual(claims["nonce"], "tool-nonce-1")
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/message_type"],
            "LtiResourceLinkRequest",
        )
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/roles"],
            ["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        )
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/resource_link"],
            {"id": self.registration.resource_link_id},
        )
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/context"],
            {
                "id": self.registration.context_id,
                "label": self.registration.context_label,
                "title": self.registration.context_title,
            },
        )
        self.assertEqual(claims["email"], "instructor1@example.org")
        self.assertEqual(claims["given_name"], "Ines")
        self.assertEqual(claims["family_name"], "Tructor")

    def test_student_role_maps_to_learner(self):
        self.user.profile.role = UserProfile.STUDENT
        self.user.profile.save()
        claims = build_claims(self.user, self.registration, tool_nonce="n")
        self.assertEqual(
            claims["https://purl.imsglobal.org/spec/lti/claim/roles"],
            ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
        )

    def test_sign_launch_jwt_is_verifiable_with_the_published_public_key(self):
        token = sign_launch_jwt(self.user, self.registration, tool_nonce="tool-nonce-1")
        platform_key = get_or_create_platform_key()
        public_key = serialization.load_pem_public_key(
            platform_key.public_key_pem.encode("utf-8")
        )

        decoded = pyjwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=self.registration.client_id,
        )
        self.assertEqual(decoded["sub"], str(self.user.id))
        self.assertEqual(decoded["nonce"], "tool-nonce-1")

        header = pyjwt.get_unverified_header(token)
        self.assertEqual(header["kid"], platform_key.kid)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python manage.py test launch.tests.JwtClaimTests -v 2
```

Expected: `ModuleNotFoundError: No module named 'launch.jwt_utils'`.

- [ ] **Step 3: Implement `launch/jwt_utils.py`**

```python
import time

import jwt

from platform_config.keys import get_or_create_platform_key

ROLE_URNS = {
    "instructor": "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
    "student": "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner",
}

LTI_CLAIM_PREFIX = "https://purl.imsglobal.org/spec/lti/claim/"


def build_claims(user, registration, tool_nonce):
    profile = user.profile
    now = int(time.time())
    return {
        "iss": registration.issuer,
        "sub": str(user.id),
        "aud": registration.client_id,
        "iat": now,
        "exp": now + 300,
        "nonce": tool_nonce,
        f"{LTI_CLAIM_PREFIX}message_type": "LtiResourceLinkRequest",
        f"{LTI_CLAIM_PREFIX}version": "1.3.0",
        f"{LTI_CLAIM_PREFIX}deployment_id": registration.deployment_id,
        f"{LTI_CLAIM_PREFIX}target_link_uri": registration.target_link_uri,
        f"{LTI_CLAIM_PREFIX}resource_link": {"id": registration.resource_link_id},
        f"{LTI_CLAIM_PREFIX}roles": [ROLE_URNS[profile.role]],
        f"{LTI_CLAIM_PREFIX}context": {
            "id": registration.context_id,
            "label": registration.context_label,
            "title": registration.context_title,
        },
        "email": user.email,
        "name": user.get_full_name(),
        "given_name": user.first_name,
        "family_name": user.last_name,
    }


def sign_launch_jwt(user, registration, tool_nonce):
    platform_key = get_or_create_platform_key()
    claims = build_claims(user, registration, tool_nonce)
    return jwt.encode(
        claims,
        platform_key.private_key_pem,
        algorithm="RS256",
        headers={"kid": platform_key.kid},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python manage.py test launch.tests.JwtClaimTests -v 2
```

Expected: `OK` (3 tests passed).

- [ ] **Step 5: Commit**

```bash
git add launch/jwt_utils.py launch/tests.py
git commit -m "Add LTI JWT claim builder and RS256 signer"
```

---

### Task 11: Auth Callback View

**Files:**
- Modify: `launch/views.py`
- Modify: `simulator/urls.py`
- Create: `launch/templates/launch/auth_callback.html`
- Test: `launch/tests.py`

- [ ] **Step 1: Write the failing tests**

Append to `launch/tests.py`:

```python
class AuthCallbackViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="erin", password="pw12345")
        self.registration = make_registration()

    def _create_launch_state(self):
        self.client.force_login(self.user)
        self.client.get(f"/launch/{self.registration.id}/init/")
        return LTILaunchState.objects.get(user=self.user, registration=self.registration)

    def test_valid_callback_signs_and_posts_jwt_then_deletes_state(self):
        launch_state = self._create_launch_state()

        response = self.client.get(
            "/auth/callback/",
            {
                "login_hint": launch_state.state,
                "client_id": self.registration.client_id,
                "nonce": "tool-nonce-xyz",
                "state": "tool-state-xyz",
                "redirect_uri": self.registration.launch_url,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.registration.launch_url)
        self.assertContains(response, "tool-state-xyz")
        self.assertFalse(LTILaunchState.objects.filter(id=launch_state.id).exists())

    def test_unknown_login_hint_returns_400(self):
        response = self.client.get(
            "/auth/callback/",
            {"login_hint": "does-not-exist", "client_id": "x", "nonce": "n", "state": "s"},
        )
        self.assertEqual(response.status_code, 400)

    def test_client_id_mismatch_returns_400(self):
        launch_state = self._create_launch_state()
        response = self.client.get(
            "/auth/callback/",
            {
                "login_hint": launch_state.state,
                "client_id": "wrong-client-id",
                "nonce": "n",
                "state": "s",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_expired_launch_state_returns_400(self):
        launch_state = self._create_launch_state()
        launch_state.created_at = timezone.now() - timedelta(minutes=10)
        launch_state.save(update_fields=["created_at"])

        response = self.client.get(
            "/auth/callback/",
            {
                "login_hint": launch_state.state,
                "client_id": self.registration.client_id,
                "nonce": "n",
                "state": "s",
            },
        )
        self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python manage.py test launch.tests.AuthCallbackViewTests -v 2
```

Expected: `404` (no route yet) on all four tests.

- [ ] **Step 3: Implement the view**

Append to `launch/views.py`:

```python
from django.http import HttpResponseBadRequest

from .jwt_utils import sign_launch_jwt


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
    return render(request, "launch/auth_callback.html", context)
```

- [ ] **Step 4: Create the template**

Create `launch/templates/launch/auth_callback.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Completing launch</title></head>
<body onload="document.forms[0].submit()">
  <p>Completing launch...</p>
  <form method="post" action="{{ launch_url }}">
    <input type="hidden" name="id_token" value="{{ id_token }}">
    <input type="hidden" name="state" value="{{ state }}">
    <button type="submit">Continue</button>
  </form>
</body>
</html>
```

- [ ] **Step 5: Wire up the URL**

In `simulator/urls.py`, add the route:

```python
    path("auth/callback/", launch_views.auth_callback, name="auth_callback"),
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python manage.py test launch.tests.AuthCallbackViewTests -v 2
```

Expected: `OK` (4 tests passed).

- [ ] **Step 7: Run the full test suite**

```bash
python manage.py test
```

Expected: `OK` with all tests across both apps passing.

- [ ] **Step 8: Commit**

```bash
git add launch/views.py launch/templates/launch/auth_callback.html simulator/urls.py launch/tests.py
git commit -m "Add auth callback that validates launch state and posts the signed LTI JWT"
```

---

### Task 12: README with Manual Test Instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

Create `README.md`:

```markdown
# LTI 1.3 Platform Simulator

A minimal Django app that acts as an LTI 1.3 platform (the Canvas side) for
testing the OpenTA2 tool's LTI 1.3 launch flow without a real Canvas instance.

See `lti13-briefing.md` for the original requirements and
`docs/superpowers/specs/2026-06-19-lti13-platform-simulator-design.md` for
the design.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Configuring a tool registration

1. Go to `http://localhost:8000/admin/` and log in as the superuser.
2. Under "LTI tool registrations," add a registration with the tool's
   OIDC init URL, launch URL, client ID, deployment ID, and the simulated
   course/context fields.
3. Set this platform's issuer (e.g. `http://localhost:8000` for local testing,
   or your public hostname if testing against a deployed tool) in the
   registration's `issuer` field — this becomes the `iss` claim the tool
   must be configured to trust.
4. The platform's public key is served at `http://localhost:8000/jwks.json`.
   Configure the tool's developer-key / platform config to fetch keys from
   that URL.

## Manual end-to-end test against a real tool (e.g. lti13.openta-demo.org)

1. Create a registration pointing at the real tool's `/oidc/init` and
   `/launch` URLs, using the `client_id` and `deployment_id` the tool
   expects from this platform.
2. Make sure the simulator is reachable from the tool (e.g. deployed
   somewhere public, or both running where the tool can reach
   `/jwks.json` over the network).
3. Log into the simulator as a non-superuser test user (give them a role
   via their User admin page's "User profile" inline).
4. Visit `/` and click the tool. You should be redirected through the
   tool's `/oidc/init`, back to this platform's `/auth/callback/`, and then
   POSTed into the tool's `/launch` with a signed `id_token`.
5. If the tool rejects the JWT, check: the tool's configured `iss` matches
   the registration's `issuer`, the `client_id` matches what's registered
   on both sides, and the tool can fetch `/jwks.json` from this platform.

## Running tests

```bash
python manage.py test
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add README with setup and manual testing instructions"
```

---

## Plan Self-Review Notes

- Spec coverage: admin tool registration ✅ (Task 6), platform keypair generation ✅ (Task 4), JWKS endpoint ✅ (Task 5), user login + tool list ✅ (Tasks 2, 8), launch-init POST to `/oidc/init` ✅ (Task 9), auth callback signing + POST to `/launch` ✅ (Task 11), JWT claims per spec ✅ (Task 10), role mapping ✅ (Task 10), state/nonce expiry validation ✅ (Tasks 7, 11).
- No placeholders: every step has complete code, exact commands, and expected output.
- Type/name consistency checked: `jwt_utils.build_claims`/`sign_launch_jwt`, `LTILaunchState.is_expired`, `UserProfile.role`/`INSTRUCTOR`/`STUDENT`, `LTIToolRegistration` field names are used identically across Tasks 6, 7, 9, 10, 11.
