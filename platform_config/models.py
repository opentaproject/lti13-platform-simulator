from django.db import models


class LTIPlatformKey(models.Model):
    kid = models.CharField(max_length=255, unique=True)
    private_key_pem = models.TextField()
    public_key_pem = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.kid
