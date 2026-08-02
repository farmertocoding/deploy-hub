"""In-memory provider fakes (§A7/§D5) — what T1 tests plug into."""
import itertools

from .base import CloudProvider, DnsProvider, EdgeProtection

_ids = itertools.count(1)


class FakeDnsProvider(DnsProvider):
    def __init__(self):
        self.zones = {}  # zone -> {record_id: record}

    def list_records(self, zone):
        return list(self.zones.get(zone, {}).values())

    def upsert_record(self, zone, name, rtype, values, *, proxied=False, ttl=None):
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
        self.zones.get(zone, {}).pop(record_id, None)  # absent == success

    def get_nameservers(self, domain):
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
