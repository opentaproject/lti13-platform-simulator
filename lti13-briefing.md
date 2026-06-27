# LTI 1.3 Platform Simulator — Claude Code Briefing

## Purpose

Build a Django app that acts as a **minimal LTI 1.3 platform** (i.e. the Canvas side) for testing an
external LTI 1.3 tool without needing a real Canvas instance. The app must simulate the LTI 1.3
OIDC launch flow so the developer can test their tool end-to-end.

---

## Background: The Real Tool Being Tested

The external LTI 1.3 tool is **OpenTA2** — a Django-based exam grading app deployed at
`lti13.openta-demo.org`. It is an LTI 1.1 Canvas external tool being upgraded to LTI 1.3.

The tool's endpoints are:
- **OIDC Init:** `https://lti13.openta-demo.org/oidc/init`
- **Launch:** `https://lti13.openta-demo.org/launch` (or course-specific e.g. `https://ffm516-2025.openta-demo.org/launch`)
- **Public JWKS:** `https://lti13.openta-demo.org/.well-known/jwks.json`

The tool's env config (for reference):
```
LTI13_AUTH_LOGIN_URL=https://canvas.chalmers.se/api/lti/authorize_redirect
LTI13_CLIENT_ID=125230000000000352
LTI13_ISSUER=https://canvas.chalmers.se
LTI13_JWKS_PUBLIC_URL=https://lti13.openta-demo.org/.well-known/jwks.json
LTI13_PRIVATE_KEY_FILE=/subdomain-data/auth/lti13-tool-private.pem
LTI13_DEPLOYMENT_ID=<pending from admin>
LTI13_KEYSET_URL=https://canvas.chalmers.se/api/lti/security/jwks
LTI13_KEY_ID=openta-lti13
LTI13_SHARED_DB_ALIAS=default
```

---

## LTI 1.3 Launch Flow (What the Simulator Must Implement)

This is the standard OpenID Connect launch flow:

1. **User clicks a tool link** in the platform (this simulator)
2. **Platform POSTs to tool's `/oidc/init`** with:
   - `iss` — platform issuer URL
   - `login_hint` — opaque user identifier
   - `lti_message_hint` — opaque launch context token
   - `target_link_uri` — where to send the user after auth
   - `client_id` — the tool's registered client ID
3. **Tool redirects to platform's auth endpoint** (`LTI13_AUTH_LOGIN_URL`) with OIDC params + `state` + `nonce`
4. **Platform validates state/nonce, signs a JWT** containing LTI claims, POSTs it to tool's `/launch`
5. **Tool validates JWT** using platform's public JWKS, then serves the user the course content

The simulator must implement steps 2 and 4 — i.e. it must:
- POST the login initiation to the tool's `/oidc/init`
- Receive the OIDC auth redirect back
- Sign and POST a valid LTI 1.3 JWT to the tool's `/launch`

---

## App Requirements

### Two user types

**Admin:**
- Log in via Django admin or a simple admin login page
- Configure one or more LTI 1.3 tool registrations, each with:
  - Tool name
  - Client ID (issued by this platform to the tool)
  - OIDC Init URL (tool's `/oidc/init`)
  - Launch/Redirect URL (tool's `/launch`)
  - Tool's Public JWKS URL (for verifying tool signatures if needed)
  - Target Link URI
  - Deployment ID
  - Issuer (this platform's issuer URL)
- The platform generates its own RSA keypair per registration (or globally) for signing JWTs
- Expose a `/jwks.json` endpoint serving the platform's public key (so the tool can verify JWTs)

**User:**
- Log in via a simple user login page
- See a list of configured LTI tools they have access to
- Click a tool → triggers the LTI 1.3 launch flow
- Receives a page with a button/link that initiates the launch POST to the tool's `/oidc/init`

### Launch page
After the user clicks a tool link, the app should render a small HTML page with a form that
auto-submits (or a button) that POSTs the login initiation parameters to the tool's `/oidc/init`.
This mimics exactly what Canvas does when a user clicks an LTI tool.

### Auth callback endpoint
The platform needs an endpoint (e.g. `/auth/callback` or `/authorize_redirect`) that:
- Receives the OIDC auth request from the tool (after `/oidc/init` redirects back)
- Validates `state` and `nonce`
- Builds and signs an LTI 1.3 JWT with standard claims (see JWT Claims below)
- POSTs the JWT as `id_token` to the tool's launch/redirect URL

### JWKS endpoint
- `GET /jwks.json` — returns the platform's public key in JWK Set format
- Used by the tool to verify the platform's JWT signatures

---

## LTI 1.3 JWT Claims (Minimum Required)

The signed JWT posted to the tool's `/launch` must include:

```json
{
  "iss": "<platform issuer>",
  "sub": "<user identifier>",
  "aud": "<client_id>",
  "iat": <now>,
  "exp": <now + 300>,
  "nonce": "<nonce from auth request>",
  "https://purl.imsglobal.org/spec/lti/claim/message_type": "LtiResourceLinkRequest",
  "https://purl.imsglobal.org/spec/lti/claim/version": "1.3.0",
  "https://purl.imsglobal.org/spec/lti/claim/deployment_id": "<deployment_id>",
  "https://purl.imsglobal.org/spec/lti/claim/target_link_uri": "<target_link_uri>",
  "https://purl.imsglobal.org/spec/lti/claim/resource_link": {
    "id": "<some stable id>"
  },
  "https://purl.imsglobal.org/spec/lti/claim/roles": [
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
  ],
  "https://purl.imsglobal.org/spec/lti/claim/context": {
    "id": "<course id>",
    "label": "<course label>",
    "title": "<course title>"
  },
  "email": "<user email>",
  "name": "<user full name>",
  "given_name": "<first name>",
  "family_name": "<last name>"
}
```

Sign with RS256 using the platform's private key. Include `kid` in the JWT header matching the
key ID in `/jwks.json`.

---

## Technical Stack

- **Django** (latest stable)
- **PostgreSQL** or SQLite for dev
- **PyJWT** or **python-jose** for JWT signing/verification
- **cryptography** library for RSA key generation
- Standard Django auth for admin/user login
- No frontend framework needed — plain HTML + minimal CSS is fine

---

## What This App Is NOT

- Not a full LMS
- Not a grade passback implementation (AGS) — out of scope for now
- Not multi-tenant — one platform instance, multiple tool registrations is enough
- No student role management beyond basic user login

---

## Reference: Canvas Developer Key Config (What Was Configured at Chalmers)

The Chalmers Canvas admin configured a Developer Key with:
- Title: OpenTA2
- Target Link URI: `https://lti13.openta-demo.org/launch`
- OIDC Init URL: `https://lti13.openta-demo.org/oidc/init`
- Public JWK URL: `https://lti13.openta-demo.org/.well-known/jwks.json`
- Placements: Account Navigation, Link Selection (Course Navigation still needed)
- Client ID issued by Canvas: `125230000000000352`

This simulator should produce an equivalent configuration flow for testing without Canvas.

---

## First Task for Claude Code

Build the Django app described above. Start with:
1. Django project scaffold with two apps: `platform_config` (admin tool registration) and `launch` (user-facing launch flow)
2. Models for `LTIToolRegistration` and `LTIPlatformKey`
3. JWKS endpoint
4. Login initiation POST page
5. Auth callback that signs and posts the JWT
6. Simple user-facing tool list page
7. Admin interface for managing tool registrations

Use SQLite for development. Generate a fresh RSA keypair on first run if none exists.
