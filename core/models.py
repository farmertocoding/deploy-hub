"""core: shared kernel. AuditEvent (§D1) plus the product models the whole
system is about — Project (code), Site (project + domain + config), Zone,
Target, SiteInstance, CheckRun, Partner — per §D9's canonical vocabulary.

core deliberately imports nothing from scanner/, deploys/ or wizard/: everything
imports core, so a dependency here becomes a dependency everywhere (see
wizard/__init__.py for the transitive-import finding that made this explicit).
vault must not import core; Target.ssh_key_ref is a vault owner-id string, not
an FK.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .validators import validate_git_url


class AuditEvent(models.Model):
    """Append-only audit trail (§D1). prev_hash chains locally; shipped_at is the off-host stamp."""

    class Source(models.TextChoices):
        UI = "ui"
        API = "api"
        CELERY = "celery"
        RECONCILER = "reconciler"
        SYSTEM = "system"
        WS = "ws"

    class Severity(models.TextChoices):
        INFO = "info"
        WARNING = "warning"
        SECURITY = "security"

    ts = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    action = models.SlugField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO)
    # Local hash chain (D-056). Genesis prev_hash=""; shipped_at is the off-host stamp.
    prev_hash = models.CharField(max_length=64, blank=True, default="")
    shipped_at = models.DateTimeField(null=True, blank=True)
    # Nullable SET_NULL: non-partner events stay, and deleting a Partner keeps the chain.
    partner = models.ForeignKey(
        "Partner", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="audit_events",
    )

    class Meta:
        indexes = [models.Index(fields=["object_type", "object_id"])]
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M:%S} {self.action}"


class RecoveryCode(models.Model):
    """One-time 2FA recovery codes, stored as sha256 hashes — a DB read (backup
    leak, SQL access) must never yield working second factors (round-1 finding;
    replaces the plaintext django-otp StaticToken storage)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="recovery_codes")
    code_hash = models.CharField(max_length=64, db_index=True)  # sha256 hex
    created = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "code_hash"], name="uniq_user_code_hash")
        ]


class Project(models.Model):
    """Code (§D9). A Project is a git URL or a local path — never a running thing."""

    class Source(models.TextChoices):
        GIT = "git"
        LOCAL_PATH = "local_path"   # dev + adopt-existing paths only

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)
    source_kind = models.CharField(max_length=16, choices=Source.choices,
                                   default=Source.GIT)
    git_url = models.CharField(max_length=2048, blank=True,
                               validators=[validate_git_url])
    git_ref = models.CharField(max_length=255, default="main")
    local_path = models.CharField(max_length=1024, blank=True)

    # Latest scan (§5.1). Kept on the Project because the report is about the CODE;
    # a Site inherits it. schema_version travels inside the payload (§D8).
    scan_report = models.JSONField(null=True, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    scan_source_fingerprint = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="projects_created")

    def __str__(self):
        return self.name


class NetworkZone(models.Model):
    """A network (§D9). Targets sit in a zone; the Hub talks to them through it."""

    class Purpose(models.TextChoices):
        PROD = "prod"
        TEST = "test"

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)
    # Default prod: existing rows fail-closed under HUB_TEST_MODE (§B9).
    purpose = models.CharField(
        max_length=16, choices=Purpose.choices, default=Purpose.PROD,
    )

    def __str__(self):
        return self.name


class DnsAccount(models.Model):
    """A DNS provider account (§2, D-034): the home of the three credential
    refs the product needs. Each ref is a vault owner id (string) — never a
    token value, and never an FK, because vault must not import core."""

    class Provider(models.TextChoices):
        CLOUDFLARE = "cloudflare"
        ROUTE53 = "route53"

    provider = models.CharField(
        max_length=32, choices=Provider.choices, default=Provider.CLOUDFLARE,
    )
    label = models.CharField(max_length=128)
    dns_token_ref = models.CharField(max_length=64, blank=True, default="")
    edge_token_ref = models.CharField(max_length=64, blank=True, default="")
    origin_ca_key_ref = models.CharField(max_length=64, blank=True, default="")

    def __str__(self):
        return f"{self.label} ({self.provider})"


class DnsZone(models.Model):
    """The single DNS-zone identity (D-033) — a DNS-provider object, never a
    NetworkZone, and never a node on the topology map (D-041)."""

    class Purpose(models.TextChoices):
        PROD = "prod"
        TEST = "test"

    account = models.ForeignKey(DnsAccount, on_delete=models.PROTECT,
                                related_name="zones")
    # Denormalized from account.provider so (provider, name) can be unique (D-056).
    provider = models.CharField(max_length=32, blank=True, default="")
    name = models.CharField(max_length=253)
    provider_zone_id = models.CharField(max_length=64, blank=True, default="")
    # Default prod: rows fail-closed under HUB_TEST_MODE, like NetworkZone (§B9).
    purpose = models.CharField(
        max_length=16, choices=Purpose.choices, default=Purpose.PROD,
    )
    proxied_default = models.BooleanField(
        default=True,
        help_text=(
            "A Cloudflare capability surfaced by the provider's capabilities() "
            "— not a provider-neutral setting."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "name"], name="uniq_dnszone_account_name",
            ),
            models.UniqueConstraint(
                fields=["provider", "name"], name="uniq_dnszone_provider_name",
            ),
        ]

    def _copy_provider_from_account(self):
        if self.account_id is None:
            return
        self.provider = self.account.provider

    def clean(self):
        """(provider, name) is unique THROUGH the account (D-033): two accounts
        of one provider must not both claim a zone name — dns_provider_for
        would have two candidate credentials for one identity."""
        self._copy_provider_from_account()
        clash = (
            DnsZone.objects.filter(
                name=self.name, account__provider=self.account.provider,
            )
            .exclude(pk=self.pk)
            .exists()
        )
        if clash:
            raise ValidationError(
                {"name": f"a {self.account.provider} zone named {self.name!r} "
                         "already exists under another account"}
            )

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        self._copy_provider_from_account()
        super().full_clean(
            exclude=exclude,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args, **kwargs):
        self._copy_provider_from_account()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.purpose})"


class Site(models.Model):
    """Project + domain + config (§D9). One Site = ONE manifest (§V5)."""

    class Exposure(models.TextChoices):
        PUBLIC = "public"
        MESH_ONLY = "mesh_only"

    class DeployStrategy(models.TextChoices):
        BLUE_GREEN = "blue_green"
        RECREATE = "recreate"

    class DeployPolicy(models.TextChoices):
        AUTO = "auto"
        CONFIRM = "confirm"
        WINDOWED = "windowed"

    class EdgeOwner(models.TextChoices):
        HOST_CADDY = "host_caddy"
        SITE_CADDY = "site_caddy"

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="sites")
    name = models.CharField(max_length=128)
    domain = models.CharField(max_length=253, blank=True)
    exposure = models.CharField(
        max_length=16, choices=Exposure.choices, default=Exposure.PUBLIC,
    )
    deploy_strategy = models.CharField(
        max_length=16, choices=DeployStrategy.choices,
        default=DeployStrategy.BLUE_GREEN,
    )
    deploy_policy = models.CharField(
        max_length=16, choices=DeployPolicy.choices, default=DeployPolicy.AUTO,
    )
    deploy_window_cron = models.CharField(max_length=128, blank=True, default="")
    maintenance_until = models.DateTimeField(null=True, blank=True)
    reconcile_enabled = models.BooleanField(default=True)
    liveness_path = models.CharField(max_length=256, blank=True, default="/healthz")
    readiness_path = models.CharField(
        max_length=256, blank=True, default="/healthz.ready",
    )
    warmup_timeout_s = models.PositiveIntegerField(default=60)
    config_stale = models.BooleanField(default=False)
    scale_ready = models.BooleanField(default=False)
    primary_target = models.ForeignKey(
        "Target", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="primary_for_sites",
    )
    # Nullable ONLY for mesh_only (check-constrained below + clean()): a public
    # site with no DnsZone has no provider to converge its records with (D-033).
    dns_zone = models.ForeignKey(
        DnsZone, null=True, blank=True, on_delete=models.PROTECT,
        related_name="sites",
    )
    proxied = models.BooleanField(default=True)
    # Who owns Caddy for this Site (D-052). Fresh Hub sites stay host_caddy;
    # adoption_plan writes site_caddy when the compose edge is unambiguous.
    edge_owner = models.CharField(
        max_length=16, choices=EdgeOwner.choices, default=EdgeOwner.HOST_CADDY,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="sites_created")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="uniq_site_name"),
            models.CheckConstraint(
                condition=models.Q(exposure="mesh_only")
                | models.Q(dns_zone__isnull=False),
                name="site_public_requires_dns_zone",
            ),
        ]

    def clean(self):
        if self.exposure != Site.Exposure.MESH_ONLY and self.dns_zone_id is None:
            raise ValidationError(
                {"dns_zone": "a public site must name its DnsZone; only "
                             "mesh_only sites may omit it"}
            )

    def __str__(self):
        return f"{self.name} ({self.domain or 'no domain yet'})"


class Partner(models.Model):
    """A partner tenant (§7 C2 / D-076). Public keys live here, not the vault."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    pubkey_current = models.TextField(blank=True, default="")
    pubkey_previous = models.TextField(blank=True, default="")
    max_sites = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1)],
    )
    deploys_per_day = models.PositiveIntegerField(
        default=50, validators=[MinValueValidator(1)],
    )
    domains = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(1)],
    )
    destination_order = models.JSONField(default=list)
    suspended = models.BooleanField(default=False)
    webhook_url = models.CharField(max_length=2048, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_sites__gte=1)
                & models.Q(deploys_per_day__gte=1)
                & models.Q(domains__gte=1),
                name="partner_quotas_finite",
            ),
        ]

    def clean(self):
        errors = {}
        for field in ("max_sites", "deploys_per_day", "domains"):
            value = getattr(self, field)
            if value is None or value < 1:
                errors[field] = "unbounded quotas are out"
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.slug


class PartnerSite(models.Model):
    """One Site bound to one Partner. Isolation is this row, not Site.tier."""

    partner = models.ForeignKey(
        Partner, on_delete=models.CASCADE, related_name="partner_sites",
    )
    site = models.OneToOneField(
        Site, on_delete=models.CASCADE, related_name="partner_site",
    )
    tenant_ref = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "tenant_ref"],
                name="uniq_partnersite_partner_tenant_ref",
            ),
        ]

    def __str__(self):
        return f"{self.partner_id}:{self.tenant_ref}"


class PartnerReplayNonce(models.Model):
    """Hub nonce cache. Unique (partner, nonce); TTL is application-level."""

    partner = models.ForeignKey(
        Partner, on_delete=models.CASCADE, related_name="replay_nonces",
    )
    nonce = models.CharField(max_length=128)
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "nonce"],
                name="uniq_partner_replay_nonce",
            ),
        ]

    def __str__(self):
        return f"{self.partner_id}:{self.nonce}"


class PartnerIdempotencyKey(models.Model):
    """Stripe-style Idempotency-Key store. Unique (partner, key); 24 h TTL is app-level."""

    partner = models.ForeignKey(
        Partner, on_delete=models.CASCADE, related_name="idempotency_keys",
    )
    key = models.CharField(max_length=255)
    params_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["partner", "key"],
                name="uniq_partner_idempotency_key",
            ),
        ]

    def __str__(self):
        return f"{self.partner_id}:{self.key}"


class Target(models.Model):
    """A managed host (§D9) — never called an instance in UI copy."""

    class Kind(models.TextChoices):
        SSH = "ssh"
        AWS_EC2 = "aws_ec2"

    class Lifecycle(models.TextChoices):
        PERMANENT = "permanent"
        EPHEMERAL = "ephemeral"

    class Status(models.TextChoices):
        PENDING = "pending"
        READY = "ready"
        ERROR = "error"
        DECOMMISSIONED = "decommissioned"

    zone = models.ForeignKey(NetworkZone, on_delete=models.PROTECT,
                             related_name="targets")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SSH)
    host = models.CharField(max_length=253)
    # CloudProvider instance id (e.g. i-…). SSH rows stay null; do not overload host.
    provider_ref = models.CharField(max_length=64, null=True, blank=True)
    ssh_user = models.CharField(max_length=64, default="root")
    # Vault owner id (string), not an FK — vault must not import core.
    ssh_key_ref = models.CharField(max_length=64, blank=True, default="")
    host_key_fingerprint = models.CharField(max_length=256, blank=True, default="")
    lifecycle = models.CharField(
        max_length=16, choices=Lifecycle.choices, default=Lifecycle.PERMANENT,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    collect_payload = models.JSONField(null=True, blank=True)
    collect_at = models.DateTimeField(null=True, blank=True)
    collect_log_inode = models.BigIntegerField(null=True, blank=True)
    collect_log_offset = models.BigIntegerField(default=0)

    def __str__(self):
        return self.host


class SiteInstance(models.Model):
    """One running copy of a Site on one Target (§D3/§D9)."""

    class DesiredState(models.TextChoices):
        RUNNING = "running"
        STOPPED = "stopped"
        ABSENT = "absent"

    class ObservedState(models.TextChoices):
        RUNNING = "running"
        STOPPED = "stopped"
        ABSENT = "absent"
        UNHEALTHY = "unhealthy"
        WARMING = "warming"

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="instances")
    target = models.ForeignKey(Target, on_delete=models.CASCADE,
                               related_name="instances")
    desired_image_tag = models.CharField(max_length=256, blank=True, default="")
    desired_state = models.CharField(
        max_length=16, choices=DesiredState.choices, default=DesiredState.ABSENT,
    )
    observed_state = models.CharField(
        max_length=16, choices=ObservedState.choices, default=ObservedState.ABSENT,
    )
    observed_at = models.DateTimeField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    internal_port = models.PositiveIntegerField(
        validators=[MinValueValidator(20000), MaxValueValidator(29999)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target", "internal_port"],
                name="uniq_siteinstance_target_port",
            ),
            models.CheckConstraint(
                condition=models.Q(internal_port__gte=20000)
                & models.Q(internal_port__lte=29999),
                name="siteinstance_internal_port_range",
            ),
        ]

    def __str__(self):
        return f"{self.site_id}@{self.target_id}:{self.internal_port}"


class OperationLock(models.Model):
    """Postgres lock row (§A5). Unique (scope, object_id, kind); INSERT-conflict refuses."""

    class Scope(models.TextChoices):
        SITE = "site"
        TARGET = "target"

    class Kind(models.TextChoices):
        DEPLOY = "deploy"
        PROVISION = "provision"
        RECONCILE = "reconcile"
        COLLECT = "collect"

    scope = models.CharField(max_length=16, choices=Scope.choices)
    object_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    holder = models.CharField(max_length=128)
    acquired_at = models.DateTimeField(auto_now_add=True)
    heartbeat_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "object_id", "kind"],
                name="uniq_operationlock_scope_object_kind",
            ),
        ]

    def __str__(self):
        return f"{self.scope}:{self.object_id}:{self.kind}"


class DnsRecord(models.Model):
    """Desired DNS for a Site (§D3). observed_* is what the provider last showed."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="dns_records")
    zone = models.ForeignKey(DnsZone, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="records")
    name = models.CharField(max_length=253)
    rtype = models.CharField(max_length=16)
    value = models.CharField(max_length=1024)
    observed_value = models.CharField(max_length=1024, blank=True, default="")
    last_verified = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name", "rtype"],
                name="uniq_dnsrecord_site_name_rtype",
            ),
        ]

    def __str__(self):
        return f"{self.name} {self.rtype}"


class SiteVolume(models.Model):
    """Named volume belonging to a Site, never to a Deployment (§N5)."""

    class BackupPolicy(models.TextChoices):
        NONE = "none"
        DIRECTORY_SYNC = "directory_sync"

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="volumes")
    name = models.CharField(max_length=128)
    container_path = models.CharField(max_length=512)
    backup_policy = models.CharField(
        max_length=32, choices=BackupPolicy.choices, default=BackupPolicy.NONE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name"], name="uniq_sitevolume_site_name",
            ),
        ]

    def __str__(self):
        return f"{self.site_id}:{self.name}"


class BackupUnit(models.Model):
    """Per-site data-backup registry (§E5/§N6). Beat stub seals dumps; ntfy is Phase 3."""

    class Kind(models.TextChoices):
        POSTGRES = "postgres"
        SQLITE_FILE = "sqlite_file"
        DIRECTORY_SYNC = "directory_sync"

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="backup_units")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    schedule = models.CharField(max_length=128, default="0 2 * * *")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "kind"], name="uniq_backupunit_site_kind",
            ),
        ]

    def __str__(self):
        return f"{self.site_id}:{self.kind}"


def _default_checkrun_results():
    return {"schema_version": 1}


class CheckRun(models.Model):
    """One scheduled or executed drill/check (HARNESS-DRILLS-BEAT)."""

    class Kind(models.TextChoices):
        HUB_DOWN = "hub_down"
        RESTORE_CLEAN = "restore_clean"
        REAPER = "reaper"
        PAGER = "pager"
        # nosec B105 — a Kind label naming what the check audits, not a credential.
        CF_TOKEN_SCOPE = "cf_token_scope"  # nosec B105
        CERT_EXPIRY = "cert_expiry"
        ADOPT = "adopt"
        SSH_ROTATE = "ssh_rotate"
        BACKUP = "backup"
        ATTACK_PLAYBOOK = "attack_playbook"
        TAILSCALE_DEVICES = "tailscale_devices"
        AWS_IAM_SCOPE = "aws_iam_scope"
        AWS_REAPER = "aws_reaper"
        PARTNER_REAPER = "partner_reaper"
        INTAKE_POLL = "intake_poll"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        SKIPPED = "skipped"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    results = models.JSONField(default=_default_checkrun_results)

    class Meta:
        indexes = [models.Index(fields=["kind", "due_at"])]

    _ADOPT_RESULT_KEYS = frozenset(
        {"schema_version", "site_id", "temp_name", "stage", "started_at"}
    )
    _BACKUP_RESULT_KEYS = frozenset(
        {"schema_version", "unit_id", "site_id", "bytes", "digest", "stored_at"}
    )

    def clean(self):
        results = self.results
        if not isinstance(results, dict) or "schema_version" not in results:
            raise ValidationError({"results": "results must include schema_version"})
        if self.kind == self.Kind.ADOPT and set(results) != self._ADOPT_RESULT_KEYS:
            raise ValidationError(
                {"results": "adopt results keys must be exactly "
                            "{schema_version, site_id, temp_name, stage, started_at}"}
            )
        if self.kind == self.Kind.BACKUP:
            if set(results) != self._BACKUP_RESULT_KEYS:
                raise ValidationError(
                    {"results": "backup results keys must be exactly "
                                "{schema_version, unit_id, site_id, bytes, digest, stored_at}"}
                )
            if type(results.get("bytes")) is not int:
                raise ValidationError({"results": "bytes must be integer size"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.kind} {self.status}"


# ── Phase 3 schema wave (design note §2). Task 1 ships fields, constraints
# and __str__s only; behaviour for these models lands in their own tasks. ──


class TlsCertificate(models.Model):
    """Certificate material record for a Site (§B6, D-035). key_ref is a vault
    owner id string, never key bytes."""

    class Mode(models.TextChoices):
        ORIGIN_CERT = "origin_cert"
        UPLOADED = "uploaded"
        AUTO = "auto"
        HUB_DNS01 = "hub_dns01"

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="tls_certificates")
    mode = models.CharField(max_length=16, choices=Mode.choices)
    not_after = models.DateTimeField(null=True, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True, default="")
    key_ref = models.CharField(max_length=64, blank=True, default="")
    pushed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.site_id}:{self.mode}#{self.fingerprint[:12]}"


class Finding(models.Model):
    """The one attention queue (§F2, D-038): every alert is a Finding with the
    same fingerprint; the pager is only the interrupt."""

    class Severity(models.TextChoices):
        P1 = "p1"
        P2 = "p2"
        P3 = "p3"

    class State(models.TextChoices):
        OPEN = "open"
        ACKED = "acked"
        RESOLVED = "resolved"
        ACCEPTED = "accepted"

    source_engine = models.CharField(max_length=64)
    severity = models.CharField(max_length=8, choices=Severity.choices)
    entity = models.CharField(max_length=128)
    title = models.CharField(max_length=256)
    body = models.TextField(blank=True, default="")
    fix_action = models.CharField(max_length=256, blank=True, default="")
    state = models.CharField(max_length=16, choices=State.choices,
                             default=State.OPEN)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    fingerprint = models.CharField(max_length=128, unique=True)
    # Accept-risk requires a one-line reason and re-surfaces on fingerprint
    # change (§F2).
    accepted_reason = models.CharField(max_length=256, blank=True, default="")

    def __str__(self):
        return f"[{self.severity}] {self.title}"


class AlertState(models.Model):
    """Hysteresis/flap/storm counters (D-038), 1:1 with a Finding by the same
    fingerprint — kept off Finding so that model stays §F2-shaped."""

    fingerprint = models.CharField(max_length=128, unique=True)
    consecutive_fail = models.PositiveIntegerField(default=0)
    consecutive_ok = models.PositiveIntegerField(default=0)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_push_at = models.DateTimeField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    transitions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"alert-state {self.fingerprint}"


class AlertDelivery(models.Model):
    """One delivery attempt of one Finding on one channel (design note §1.6)."""

    class Channel(models.TextChoices):
        NTFY = "ntfy"
        EMAIL = "email"

    finding = models.ForeignKey(Finding, on_delete=models.CASCADE,
                                related_name="deliveries")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    severity = models.CharField(max_length=8, choices=Finding.Severity.choices)
    backend = models.CharField(max_length=64, blank=True, default="")
    sent_at = models.DateTimeField(default=timezone.now)
    ok = models.BooleanField(default=False)
    detail = models.CharField(max_length=512, blank=True, default="")

    def __str__(self):
        return f"{self.channel}:{self.finding_id} ok={self.ok}"


class HostMetric(models.Model):
    """Per-target host samples. ts is Hub persist clock (design note §2 / C3)."""

    target = models.ForeignKey(
        Target, on_delete=models.CASCADE, related_name="host_metrics",
    )
    ts = models.DateTimeField(db_index=True)
    cpu = models.FloatField(null=True)
    ram = models.FloatField(null=True)
    disk = models.FloatField(null=True)
    load = models.FloatField(null=True)
    cores = models.PositiveIntegerField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["target", "-ts"]),
        ]

    def __str__(self):
        return f"{self.target_id}@{self.ts}"


class UptimeEvent(models.Model):
    """State transitions the hysteresis engine reads (design note §1.8)."""

    entity = models.CharField(max_length=128)
    kind = models.CharField(max_length=32)
    state = models.CharField(max_length=32)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"{self.entity} {self.kind}={self.state}"


class TrafficStat(models.Model):
    """Per-site traffic buckets (§C4). sampled=True marks the byte-cap degrade
    path's summary rows."""

    class Granularity(models.TextChoices):
        MINUTE = "minute"
        HOUR = "hour"
        DAY = "day"

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="traffic_stats")
    bucket_start = models.DateTimeField(db_index=True)
    granularity = models.CharField(
        max_length=16, choices=Granularity.choices, default=Granularity.MINUTE,
    )
    requests = models.BigIntegerField(default=0)
    bytes = models.BigIntegerField(default=0)
    status_counts = models.JSONField(default=dict, blank=True)
    sampled = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.site_id}@{self.bucket_start:%Y-%m-%d %H:%M} ({self.granularity})"
