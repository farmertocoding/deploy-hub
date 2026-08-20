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


class Deployment(models.Model):
    """One attempt to converge a Site to a Manifest (§D2). History is append-only."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        ROLLED_BACK = "rolled_back"
        CANCELLED = "cancelled"
        SUPERSEDED = "superseded"

    manifest = models.ForeignKey(
        Manifest, on_delete=models.CASCADE, related_name="deployments",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED,
    )
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    rollback_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="rollbacks",
    )

    def __str__(self):
        return f"deployment {self.pk} {self.status}"


class DeploymentStep(models.Model):
    """One named step of a Deployment (§D2). Resume = first non-succeeded step."""

    class Name(models.TextChoices):
        BUILD = "build"
        SHIP = "ship"
        MIGRATE = "migrate"
        START_GREEN = "start_green"
        HEALTH_CHECK = "health_check"
        DNS = "dns"
        ROUTE_TLS = "route_tls"
        SMOKE_TEST = "smoke_test"
        CUTOVER = "cutover"

    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        SKIPPED = "skipped"

    deployment = models.ForeignKey(
        Deployment, on_delete=models.CASCADE, related_name="steps",
    )
    seq = models.PositiveIntegerField()
    name = models.CharField(max_length=32, choices=Name.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)
    log_text = models.TextField(blank=True, default="")
    artifacts = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["deployment", "seq"], name="uniq_deploymentstep_deployment_seq",
            ),
        ]
        ordering = ["seq"]

    def __str__(self):
        return f"{self.deployment_id}:{self.seq}:{self.name}"


class DeploymentArtifact(models.Model):
    """Inline text artifact for a Deployment (§D2). Kilobytes; no object storage."""

    deployment = models.ForeignKey(
        Deployment, on_delete=models.CASCADE, related_name="text_artifacts",
    )
    kind = models.CharField(max_length=64)
    content = models.TextField()

    def __str__(self):
        return f"{self.deployment_id}:{self.kind}"
