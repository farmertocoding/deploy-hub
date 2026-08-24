"""In-memory provider fakes (§A7/§D5) — what T1 tests plug into."""
import itertools
import os

from .base import (
    CloudProvider,
    DnsProvider,
    EdgeProtection,
    ImageRegistry,
    OriginCertIssuer,
    Pager,
)

_ids = itertools.count(1)


class FakeDnsProvider(DnsProvider):
    """Zone keys may be strings, NetworkZones, or DnsZone rows — whatever the
    caller hands over is recorded verbatim in `calls`, so tests can assert
    the pipeline passed a DnsZone and never a NetworkZone (Task 1).

    ``custom_hostname=True`` adds the D-079 capability; the default Fake
    omits it (same as Route 53).
    """

    _MUTATING = {"upsert_record", "delete_record", "create_custom_hostname"}

    def __init__(self, *, custom_hostname=False):
        self.zones = {}  # zone -> {record_id: record}
        self.calls = []  # (method, zone-or-domain, *args)
        self.hostnames = {}
        self._custom_hostname = bool(custom_hostname)

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
        caps = {"proxied"}
        if self._custom_hostname:
            caps.add("custom_hostname")
        return caps

    def _require_custom_hostname(self):
        from .custom_hostname import CustomHostnameError

        if "custom_hostname" not in self.capabilities():
            raise CustomHostnameError("custom_hostname capability is off")

    def _txt_present(self, name, value):
        want_name = str(name or "").rstrip(".").lower()
        want_value = str(value or "")
        for records in self.zones.values():
            for rec in records.values():
                if rec["rtype"] != "TXT":
                    continue
                if rec["name"].rstrip(".").lower() != want_name:
                    continue
                values = [str(item) for item in rec["values"]]
                if want_value in values:
                    return True
        return False

    def create_custom_hostname(self, hostname):
        from .custom_hostname import (
            CustomHostnameError,
            ownership_txt,
            refuse_partner_base_collision,
        )

        self._require_custom_hostname()
        host = str(hostname or "").rstrip(".").lower()
        refuse_partner_base_collision(host)
        self.calls.append(("create_custom_hostname", host))
        if host in self.hostnames:
            raise CustomHostnameError(f"custom hostname {host!r} already exists")
        txt = ownership_txt(host, f"own-{next(_ids)}")
        rec = {
            "id": f"chn-{next(_ids)}",
            "hostname": host,
            "status": "pending",
            "ownership_verification": txt,
        }
        self.hostnames[host] = rec
        return dict(rec)

    def custom_hostname_status(self, hostname):
        from .custom_hostname import CustomHostnameError

        self._require_custom_hostname()
        host = str(hostname or "").rstrip(".").lower()
        rec = self.hostnames.get(host)
        if rec is None:
            raise CustomHostnameError(f"unknown custom hostname {host!r}")
        self.calls.append(("custom_hostname_status", host))
        txt = rec["ownership_verification"]
        if self._txt_present(txt["name"], txt["value"]):
            rec["status"] = "active"
        return rec["status"]

    def custom_hostname_txt(self, hostname):
        from .custom_hostname import CustomHostnameError

        self._require_custom_hostname()
        host = str(hostname or "").rstrip(".").lower()
        rec = self.hostnames.get(host)
        if rec is None:
            raise CustomHostnameError(f"unknown custom hostname {host!r}")
        self.calls.append(("custom_hostname_txt", host))
        return dict(rec["ownership_verification"])

    def serve_custom_hostname(self, hostname):
        from .custom_hostname import caddy_route_for

        self._require_custom_hostname()
        return caddy_route_for(self, hostname)


class FakeEdgeProtection(EdgeProtection):
    _MUTATING = {"set_security_level", "ban_ip", "purge_cache"}

    def __init__(self):
        self.security_level = {}
        self.banned = []
        self.purges = []
        self.calls = []

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def set_security_level(self, zone, level):
        self.calls.append(("set_security_level", zone, level))
        self.security_level[zone] = level

    def ban_ip(self, zone, ip, *, note=""):
        self.calls.append(("ban_ip", zone, ip, note))
        self.banned.append((zone, ip, note))

    def purge_cache(self, zone):
        self.calls.append(("purge_cache", zone))
        self.purges.append(zone)


class FakeCloudProvider(CloudProvider):
    def __init__(self):
        self.instances = {}

    def create_instance(self, spec):
        iid = f"i-{next(_ids)}"
        self.instances[iid] = {
            "id": iid,
            "state": "running",
            "public_ip": "203.0.113.10",
            "host_key_fingerprint": "SHA256:fakehostkeyfingerprint",
            "host_keys": ["ssh-ed25519 FAKEKEY"],
            "spec": spec,
            "ingress": [],
        }
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


class FakeTailscale:
    """In-memory Tailscale device list for T1 (D-058)."""

    def __init__(self, devices=None):
        self.devices = list(devices or [])
        self.calls = []

    def list_devices(self, *, timeout=20):
        self.calls.append(("list_devices", timeout))
        return [dict(row) for row in self.devices]


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


class FakeImageRegistry(ImageRegistry):
    """T1 registry: TLS + auth required; push cred is never a pull cred.

    Construction refuses tls=False, auth=False, a non-https URL, or an
    empty push password. A push-open Fake is not constructible.
    """

    _MUTATING = {"push"}
    _PUSH_USER = "hub-push"
    # nosec B105 — T1 Fake push password, never a live credential.
    _PUSH_PASSWORD = "hub-push-secret-not-for-targets"  # nosec B105

    def __init__(
        self,
        *,
        url="https://registry.test",
        tls=True,
        auth=True,
        push_username=None,
        push_password=None,
    ):
        url = str(url or "").strip()
        if not tls or not url.startswith("https://"):
            raise ValueError("FakeImageRegistry requires TLS (https)")
        if push_username is None:
            push_username = self._PUSH_USER
        if push_password is None:
            push_password = self._PUSH_PASSWORD
        push_username = str(push_username)
        push_password = str(push_password)
        if not auth or not push_username or not push_password:
            raise ValueError("FakeImageRegistry requires auth")
        self.url = url
        self.push_username = push_username
        self.push_password = push_password
        self.images = {}
        self.calls = []

    def capabilities(self):
        return {"tls", "auth"}

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def push(self, tag, archive):
        self.calls.append(("push", tag))
        self.images[tag] = archive
        return {"url": self._image_url(tag)}

    def pull_spec(self, tag, *, target):
        self.calls.append(("pull_spec", tag, target))
        ident = _registry_target_ident(target)
        username = f"pull-only-{ident}"
        password = f"pull-only-secret-{ident}"
        if username == self.push_username or password == self.push_password:
            raise RuntimeError("push cred must not equal pull cred")
        return {
            "url": self._image_url(tag),
            "username": username,
            "password": password,
        }

    def _image_url(self, tag):
        host = self.url.split("://", 1)[-1].rstrip("/")
        return f"{host}/deploy-hub/{tag}"


def _registry_target_ident(target):
    if target is None:
        return "none"
    pk = getattr(target, "pk", None)
    if pk is not None:
        return str(pk)
    return str(target)


class FakeSsm:
    """In-memory SSM port for T1. Paths are /deploy-hub/{target.pk}/… only.

    `.fail = True` raises on Put/Delete so the playbook can file ssm-fail
    without a value in the exception.
    """

    _MUTATING = frozenset({"put_parameter", "delete_parameter", "add_tags"})

    def __init__(self, *, target=None, fail=False):
        self.target = target
        self.fail = fail
        self.parameters = {}
        self.tags = {}
        self.calls = []

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def put_parameter(self, name, value, *, tags=None, overwrite=True):
        from .ssm import SsmError, assert_parameter_path

        assert_parameter_path(name, target=self.target)
        if self.fail:
            raise SsmError("fake ssm unavailable")
        if overwrite is False and name in self.parameters:
            raise SsmError("parameter already exists")
        if self.parameters.get(name) == ("" if value is None else str(value)):
            self.calls.append(("get_parameter", name))
            return
        self.calls.append(("put_parameter", name))
        self.parameters[name] = "" if value is None else str(value)
        if tags:
            self.calls.append(("add_tags", name))
            self.tags[name] = {str(k): str(v) for k, v in tags.items()}

    def get_parameter(self, name):
        from .ssm import ParameterNotFound, assert_parameter_path

        assert_parameter_path(name, target=self.target)
        self.calls.append(("get_parameter", name))
        if name not in self.parameters:
            raise ParameterNotFound("parameter not found")
        return self.parameters[name]

    def delete_parameter(self, name):
        from .ssm import SsmError, assert_parameter_path

        assert_parameter_path(name, target=self.target)
        if self.fail:
            raise SsmError("fake ssm unavailable")
        self.calls.append(("delete_parameter", name))
        self.parameters.pop(name, None)
