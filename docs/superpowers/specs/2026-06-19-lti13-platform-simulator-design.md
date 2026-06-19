# LTI 1.3 Platform Simulator — Design

Date: 2026-06-19

## Purpose

A minimal Django app that acts as an LTI 1.3 platform (the Canvas side) so the
OpenTA2 tool (`lti13.openta-demo.org`) can be tested end-to-end without a real
Canvas instance. It implements the OIDC-based LTI 1.3 launch flow: login
initiation to the tool's `/oidc/init`, and signing/posting the LTI JWT to the
tool's `/launch`.

Source requirements: `lti13-briefing.md` (repo root).

## Non-goals

- Not a full LMS
- No AGS (grade passback)
- Not multi-tenant (one platform instance, multiple tool registrations)
- No student role management beyond a single role field per user

## Project layout

Django project `simulator`, two apps:

- `platform_config` — admin-side concerns: tool registration, signing key,
  JWKS endpoint
- `launch` — user-side concerns: tool list, launch initiation, OIDC auth
  callback, launch state tracking, user profile/role

## Models

### `platform_config.LTIPlatformKey`

- `kid` — str, e.g. `"platform-key-1"`
- `private_key_pem` — text
- `public_key_pem` — text
- `created_at` — datetime

Exactly one row is expected to exist. A helper
(`get_or_create_platform_key()`) generates a fresh RSA-2048 keypair via the
`cryptography` library and creates this row the first time it's needed (JWKS
endpoint, or JWT signing) if no row exists yet. No management command or
fixture required.

### `platform_config.LTIToolRegistration`

- `name` — str
- `client_id` — str (the client ID this platform issues to the tool)
- `oidc_init_url` — URL (tool's `/oidc/init`)
- `launch_url` — URL (tool's `/launch`)
- `tool_jwks_url` — URL (tool's public JWKS, stored for reference; not
  required for the launch flow itself since the platform doesn't need to
  verify anything signed by the tool in this flow)
- `target_link_uri` — URL
- `deployment_id` — str
- `issuer` — str (this platform's issuer URL, used as `iss` claim)
- `context_id`, `context_label`, `context_title` — str (the simulated course)
- `resource_link_id` — str (stable per-registration resource link id)

One registration = one fixed simulated course/resource link. No separate
`Course` model.

### `launch.UserProfile`

- `user` — OneToOneField → `User`
- `role` — choices: `instructor` / `student`, drives the LTI roles claim

Created via Django admin alongside the `User`, or a signal that
auto-creates a profile (default role `student`) when a `User` is created —
implementation detail to settle in the plan, not the design.

### `launch.LTILaunchState`

- `state` — random unique token (platform's own state, used as the
  `login_hint` we hand the tool)
- `nonce` — random token (platform's own nonce; not the security-critical
  one — see Auth callback below)
- `user` — FK → `User`
- `registration` — FK → `LTIToolRegistration`
- `created_at` — datetime

One row per in-flight launch attempt. Looked up by `state` (echoed back by
the tool as `login_hint`) in the auth callback, then deleted once consumed.
Rows older than 5 minutes are treated as expired and rejected even if found.

## Flows

### Tool list

`launch` app, `@login_required`. Lists all `LTIToolRegistration` rows with a
link to that registration's launch-init view.

### Launch-init view — `/launch/<registration_id>/init/`

1. Create an `LTILaunchState` row for `(request.user, registration)` with a
   fresh `state` and `nonce`.
2. Render an HTML page with an auto-submitting form (or button) that POSTs to
   `registration.oidc_init_url` with:
   - `iss` = `registration.issuer`
   - `login_hint` = the `LTILaunchState.state` token
   - `lti_message_hint` = the same token (no need for it to differ from
     `login_hint` in this simulator)
   - `target_link_uri` = `registration.target_link_uri`
   - `client_id` = `registration.client_id`

### Auth callback — `/auth/callback/`

The tool's OIDC library redirects the browser here (GET) after receiving the
login-init POST, per the LTI 1.3 / OIDC third-party login spec, with query
params it generates: `client_id`, `redirect_uri`, `login_hint`, `state`
(tool's own state, distinct from ours), `nonce` (tool's own nonce),
`response_type`, etc.

Steps:

1. Look up `LTILaunchState` by `state == request.GET["login_hint"]`. 400 if
   not found or older than 5 minutes.
2. Validate `request.GET["client_id"] == launch_state.registration.client_id`.
   400 on mismatch.
3. Build the LTI JWT claims (see below), using the tool's `nonce` (from
   `request.GET["nonce"]`) as the JWT `nonce` claim — this is what the tool
   will actually check.
4. Sign with RS256 using the platform key, `kid` in the JWT header.
5. Render an auto-submitting HTML form POSTing `id_token` (the JWT) and
   `state` (the tool's `state` from `request.GET`, echoed back unchanged) to
   `request.GET["redirect_uri"]` (falls back to `launch_state.registration.launch_url`
   if the tool didn't send one).
6. Delete the `LTILaunchState` row.

### JWT claims

```json
{
  "iss": "<registration.issuer>",
  "sub": "<request.user.id, stringified>",
  "aud": "<registration.client_id>",
  "iat": <now>,
  "exp": <now + 300>,
  "nonce": "<tool's nonce from the auth request>",
  "https://purl.imsglobal.org/spec/lti/claim/message_type": "LtiResourceLinkRequest",
  "https://purl.imsglobal.org/spec/lti/claim/version": "1.3.0",
  "https://purl.imsglobal.org/spec/lti/claim/deployment_id": "<registration.deployment_id>",
  "https://purl.imsglobal.org/spec/lti/claim/target_link_uri": "<registration.target_link_uri>",
  "https://purl.imsglobal.org/spec/lti/claim/resource_link": {"id": "<registration.resource_link_id>"},
  "https://purl.imsglobal.org/spec/lti/claim/roles": ["<LTI role URN derived from profile.role>"],
  "https://purl.imsglobal.org/spec/lti/claim/context": {
    "id": "<registration.context_id>",
    "label": "<registration.context_label>",
    "title": "<registration.context_title>"
  },
  "email": "<user.email>",
  "name": "<user.get_full_name()>",
  "given_name": "<user.first_name>",
  "family_name": "<user.last_name>"
}
```

Role mapping:
- `instructor` → `http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor`
- `student` → `http://purl.imsglobal.org/vocab/lis/v2/membership#Learner`

### JWKS endpoint — `GET /jwks.json`

Loads the platform key, converts the RSA public key to JWK format (modulus
`n`, exponent `e`, base64url-encoded, `kty: RSA`, `use: sig`, `alg: RS256`,
`kid` matching the signing key), returns `{"keys": [...]}`.

## Admin

- `LTIToolRegistration`: full CRUD via Django admin
- `LTIPlatformKey`: read-only in admin (list/detail show `kid` and public key
  only; private key field marked read-only in the admin form so it can't be
  edited away, though Django admin alone doesn't hide field *values* from
  staff who can view it — acceptable for a local dev tool)
- `UserProfile`: edit inline on the `User` admin page (role field)
- Login: Django's built-in `/admin/`

## Error handling

- Auth callback: 400 with plain-text/HTML message for unknown/expired
  `login_hint`, or `client_id` mismatch. No retries — this is a dev tool, a
  clear error is sufficient.
- No other endpoints need bespoke error handling beyond Django defaults.

## Testing

No real Canvas or live OpenTA2 instance is reachable from this environment,
so testing is split:

- Automated: unit tests for JWT claim construction + signing (verify
  signature against the public JWK produced by the JWKS endpoint), and for
  `LTILaunchState` validation (valid, expired, mismatched client_id, unknown
  login_hint).
- Manual: a short README section describing how to point a real
  `LTIToolRegistration` row at `lti13.openta-demo.org` and walk through a live
  launch once deployed.

## Tech stack

- Django (latest stable), SQLite for dev
- `PyJWT` for JWT signing
- `cryptography` for RSA key generation and JWK export
- Plain HTML + minimal CSS, no frontend framework
