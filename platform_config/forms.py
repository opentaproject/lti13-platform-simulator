import uuid

from django import forms


def _default_client_id():
    return f"client-{uuid.uuid4().hex[:12]}"


def _default_deployment_id():
    return f"deployment-{uuid.uuid4().hex[:12]}"


def _default_resource_link_id():
    return f"resource-{uuid.uuid4().hex[:12]}"


class ToolRegistrationImportForm(forms.Form):
    config_url = forms.URLField(
        label="Config URL",
        help_text="URL to the tool's LTI 1.3 config JSON, for example /lti13/config.json.",
    )
    client_id = forms.CharField(
        label="Client ID",
        required=False,
        initial=_default_client_id,
        help_text="Optional. Leave blank to generate a simulator-side client ID.",
    )
    deployment_id = forms.CharField(
        label="Deployment ID",
        required=False,
        initial=_default_deployment_id,
        help_text="Optional. Leave blank to generate a simulator-side deployment ID.",
    )
    issuer = forms.URLField(
        label="Issuer",
        required=False,
        help_text="Optional. Defaults to this simulator's base URL.",
    )
    resource_link_id = forms.CharField(
        label="Resource Link ID",
        required=False,
        initial=_default_resource_link_id,
        help_text="Optional. Leave blank to generate a resource link id.",
    )

