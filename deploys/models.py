"""deploys: the pipeline's own models.

§V6 boundary — READ BEFORE ADDING AN IMPORT HERE. This package never imports scanner.
The wizard materializes every module output (dockerfile_template included) into
Manifest.body; the pipeline reads only that frozen row. Enforced by
tests/test_import_rule.py, which follows the import graph rather than grepping for a
direct `import scanner` line.
"""
from django.conf import settings
from django.db import models

from core.models import Site

MANIFEST_SCHEMA_VERSION = 1


class Manifest(models.Model):
    """A frozen, versioned deployment manifest — append-only.

    Never updated in place. A wizard change materializes version N+1, so a deploy that
    is mid-flight cannot have the ground move under it, and rollback has something
    real to roll back TO. This is the §D2 append-only-history rule applied one level
    up from Deployment rows.
    """

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="manifests")
    version = models.PositiveIntegerField()
    schema_version = models.PositiveIntegerField(default=MANIFEST_SCHEMA_VERSION)
    body = models.JSONField()

    # Which scan produced the module outputs frozen into body — the provenance a
    # reviewer needs to answer "why does the manifest say that?".
    scan_report_hash = models.CharField(max_length=64, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="manifests_created")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "version"],
                                    name="uniq_manifest_site_version")
        ]
        ordering = ["-version"]

    def __str__(self):
        return f"{self.site.name} manifest v{self.version}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            # Belt-and-braces: an in-place edit would silently rewrite the artifact a
            # completed deploy claims to have used.
            raise ValueError(
                "Manifest rows are append-only — materialize a new version instead"
            )
        super().save(*args, **kwargs)
