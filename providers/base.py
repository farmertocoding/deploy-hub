"""Provider interfaces, pinned before any implementation (§D5).

Hard rule (§D4, enforced by tests/test_import_rule.py): boto3 / azure-* / Cloudflare
clients import ONLY under providers/.
"""


class DnsProvider:
    def list_records(self, zone):
        raise NotImplementedError

    def upsert_record(self, zone, name, rtype, values, *, proxied=False, ttl=None):
        raise NotImplementedError

    def delete_record(self, zone, record_id):
        raise NotImplementedError

    def get_nameservers(self, domain):
        raise NotImplementedError

    def capabilities(self):
        return set()


class EdgeProtection:
    """Implemented ONLY by Cloudflare (§D5). Playbooks take `EdgeProtection | None`
    and degrade to notify-only explicitly, in code — never a silent no-op."""

    def set_security_level(self, zone, level):
        raise NotImplementedError

    def ban_ip(self, zone, ip, *, note=""):
        raise NotImplementedError

    def purge_cache(self, zone):
        raise NotImplementedError


class CloudProvider:
    def create_instance(self, spec):
        """Return {id, state, public_ip, host_key_fingerprint} (+ optional host_keys)."""
        raise NotImplementedError

    def get_instance(self, instance_id):
        raise NotImplementedError

    def terminate_instance(self, instance_id):
        """Idempotent: already-absent == success (the reaper depends on it)."""
        raise NotImplementedError

    def ensure_ingress_rules(self, instance_id, rules):
        raise NotImplementedError

    def list_tagged_instances(self, tags):
        raise NotImplementedError

    def create_image(self, instance_id, name):
        raise NotImplementedError

    def estimate_hourly_cost(self, spec):
        raise NotImplementedError


class Pager:
    """One-call publish seam (D-036). Implementations live under providers/."""

    def publish(self, severity, title, body, *, tags, click_url):
        raise NotImplementedError


class OriginCertIssuer:
    """Hub-side Origin CA issuance (D-035). The Hub generates the keypair
    and sends only the CSR; the issuer returns the signed certificate."""

    def issue(self, zone, hostnames, *, validity_days, csr):
        """Return ``{"certificate": pem, "expires_at": datetime}``."""
        raise NotImplementedError
