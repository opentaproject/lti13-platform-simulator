import json
import time

import jwt

from platform_config.keys import get_or_create_platform_key

ROLE_URNS = {
    "instructor": "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
    "student": "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner",
}

LTI_CLAIM_PREFIX = "https://purl.imsglobal.org/spec/lti/claim/"


def build_claims(user, registration, tool_nonce, *, target_link_uri=None, context=None):
    profile = user.profile
    now = int(time.time())
    context = context or {}
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
        f"{LTI_CLAIM_PREFIX}target_link_uri": target_link_uri or registration.target_link_uri,
        f"{LTI_CLAIM_PREFIX}resource_link": {"id": registration.resource_link_id},
        f"{LTI_CLAIM_PREFIX}roles": [ROLE_URNS[profile.role]],
        f"{LTI_CLAIM_PREFIX}context": {
            "id": context.get("id", ""),
            "label": context.get("label", ""),
            "title": context.get("title", ""),
        },
        "email": user.email,
        "name": user.get_full_name(),
        "given_name": user.first_name,
        "family_name": user.last_name,
    }


def sign_launch_jwt(user, registration, tool_nonce, *, target_link_uri=None, context=None):
    claims = build_claims(
        user,
        registration,
        tool_nonce,
        target_link_uri=target_link_uri,
        context=context,
    )
    return sign_claims(claims)


def sign_claims(claims):
    platform_key = get_or_create_platform_key()
    print(f"LTI JWT payload:\n{json.dumps(claims, indent=2)}")
    return jwt.encode(
        claims,
        platform_key.private_key_pem,
        algorithm="RS256",
        headers={"kid": platform_key.kid},
    )
