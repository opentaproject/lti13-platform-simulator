from django.db import models


class LTIPlatformKey(models.Model):
    kid = models.CharField(max_length=255, unique=True)
    private_key_pem = models.TextField()
    public_key_pem = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.kid


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
