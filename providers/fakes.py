"""In-memory provider fakes (§A7/§D5) — what T1 tests plug into."""
import itertools
import os

from .base import CloudProvider, DnsProvider, EdgeProtection, OriginCertIssuer, Pager

_ids = itertools.count(1)


class FakeDnsProvider(DnsProvider):
    """Zone keys may be strings, NetworkZones, or DnsZone rows — whatever the
    caller hands over is recorded verbatim in `calls`, so tests can assert
    the pipeline passed a DnsZone and never a NetworkZone (Task 1)."""

    _MUTATING = {"upsert_record", "delete_record"}

    def __init__(self):
        self.zones = {}  # zone -> {record_id: record}
        self.calls = []  # (method, zone-or-domain, *args)

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def list_records(self, zone):
        self.calls.append(("list_records", zone))
        return list(self.zones.get(zone, {}).values())

    def upsert_record(self, zone, name, rtype, values, *, proxied=False, ttl=None):
        self.calls.append(("upsert_record", zone, name, rtype, list(values),
                           proxied, ttl))
        records = self.zones.setdefault(zone, {})
        for rid, rec in records.items():
            if rec["name"] == name and rec["rtype"] == rtype:
                rec.update(values=values, proxied=proxied, ttl=ttl)
                return rid
        rid = f"rec-{next(_ids)}"
        records[rid] = {
            "id": rid, "name": name, "rtype": rtype,
            "values": values, "proxied": proxied, "ttl": ttl,
        }
        return rid

    def delete_record(self, zone, record_id):
        self.calls.append(("delete_record", zone, record_id))
        self.zones.get(zone, {}).pop(record_id, None)  # absent == success

    def get_nameservers(self, domain):
        self.calls.append(("get_nameservers", domain))
        return ["fake.ns1.example", "fake.ns2.example"]

    def capabilities(self):
        return {"proxied"}


class FakeEdgeProtection(EdgeProtection):
    def __init__(self):
        self.security_level = {}
        self.banned = []
        self.purges = []

    def set_security_level(self, zone, level):
        self.security_level[zone] = level

    def ban_ip(self, zone, ip, *, note=""):
        self.banned.append((zone, ip, note))

    def purge_cache(self, zone):
        self.purges.append(zone)


class FakeCloudProvider(CloudProvider):
    def __init__(self):
        self.instances = {}

    def create_instance(self, spec):
        iid = f"i-{next(_ids)}"
        self.instances[iid] = {"id": iid, "spec": spec, "state": "running",
                               "host_keys": ["ssh-ed25519 FAKEKEY"], "ingress": []}
        return self.instances[iid]

    def get_instance(self, instance_id):
        return self.instances.get(instance_id)

    def terminate_instance(self, instance_id):
        self.instances.pop(instance_id, None)  # idempotent: absent == success

    def ensure_ingress_rules(self, instance_id, rules):
        if instance_id in self.instances:
            self.instances[instance_id]["ingress"] = list(rules)

    def list_tagged_instances(self, tags):
        return [i for i in self.instances.values()
                if all(i["spec"].get("tags", {}).get(k) == v for k, v in tags.items())]

    def create_image(self, instance_id, name):
        return {"image_id": f"img-{next(_ids)}", "name": name}

    def estimate_hourly_cost(self, spec):
        return 0.05


class FakePager(Pager):
    """Records publishes. Default backend in tests so nothing pages anyone."""

    def __init__(self):
        self.published = []
        self.fail = False

    def publish(self, severity, title, body, *, tags, click_url, **_kwargs):
        record = {
            "severity": severity,
            "title": title,
            "body": body,
            "tags": tags,
            "click_url": click_url,
        }
        self.published.append(record)
        if self.fail:
            raise RuntimeError("fake pager failed")
        return record


class FakeOriginCertIssuer(OriginCertIssuer):
    """Locally-minted leaf so T1/T2 never call Cloudflare. The leaf public
    key is taken from the Hub CSR so key/cert match still holds."""

    def __init__(self):
        self.calls = []

    def issue(self, zone, hostnames, *, validity_days, csr):
        from vault.tls import mint_local_leaf

        self.calls.append((zone, list(hostnames), validity_days))
        certificate, expires_at = mint_local_leaf(
            csr, hostnames, validity_days=validity_days,
        )
        return {"certificate": certificate, "expires_at": expires_at}


class FakeKms:
    """In-memory KMS port for T1. Bulk crypto stays under vault/.

    `.down = True` is the KMS blip: encrypt/decrypt raise, so a get() that
    still succeeds is proving the process-memory DEK cache, not the fake.
    """

    def __init__(self, key_id="alias/hub-test"):
        self.key_id = key_id
        self.down = False
        self.encrypt_calls = 0
        self.decrypt_calls = 0
        self._blobs = {}

    def _raise_if_down(self):
        if self.down:
            raise RuntimeError("fake kms unavailable")

    def check(self):
        self._raise_if_down()
        return True

    def encrypt(self, plaintext: bytes) -> bytes:
        self._raise_if_down()
        self.encrypt_calls += 1
        token = os.urandom(16)
        self._blobs[token] = plaintext
        return b"fakekms:" + token

    def decrypt(self, ciphertext: bytes) -> bytes:
        self._raise_if_down()
        self.decrypt_calls += 1
        prefix = b"fakekms:"
        if not ciphertext.startswith(prefix):
            raise RuntimeError("fake kms: unknown ciphertext")
        token = ciphertext[len(prefix) :]
        try:
            return self._blobs[token]
        except KeyError as exc:
            raise RuntimeError("fake kms: unknown ciphertext") from exc
