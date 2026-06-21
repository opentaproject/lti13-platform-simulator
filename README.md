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
