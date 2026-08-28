"""Product Route 53 DNS adapter (D-065, C6, C7) — DnsProvider only.

Constructed ONLY by providers.registry.dns_provider_for, which enforces the
purpose wall, dns_token_ref == AWS_CREDENTIALS_REF, and CLOUD_CREDENTIAL load
before this class exists. The client is bound to exactly one DnsZone and
refuses calls that name a different one. Changes go only to
DnsZone.provider_zone_id.

Not an EdgeProtection. capabilities() omits proxied; upsert_record(...,
proxied=True) raises and does not write an unproxied A. Credentials appear in
boto3.client kwargs and nowhere else: not in repr, not in logs, not in
Finding bodies.
"""
import os
from contextlib import contextmanager

import boto3
from botocore.exceptions import ClientError

from core.models import default_workspace

from .aws_creds import boto3_client
from .base import DnsProvider

DEFAULT_TTL = 300
DEFAULT_REGION = "us-east-1"


class Route53Error(RuntimeError):
    """A Route 53 call or capability refusal. Never carries credentials."""


def hosted_zone_id(value):
    """Bare hosted-zone id: strip a leading /hostedzone/ if present."""
    return str(value or "").strip().rsplit("/", 1)[-1]


def _bare_name(name):
    return str(name or "").rstrip(".").lower()


def _fqdn(name):
    text = str(name or "").strip()
    if text and not text.endswith("."):
        return text + "."
    return text


def _error_code(error):
    resp = getattr(error, "response", None)
    if isinstance(resp, dict):
        return str((resp.get("Error") or {}).get("Code") or "")
    return ""


def _record_id(name, rtype, set_identifier=None):
    rid = f"{_bare_name(name)}|{rtype}"
    if set_identifier:
        return f"{rid}|{set_identifier}"
    return rid


def file_r53_fail(zone, error):
    """kind r53-fail, fingerprint r53-fail:{zone.pk}. Refs, never tokens."""
    from monitor.alerts import raise_alert

    ref = str(getattr(getattr(zone, "account", None), "dns_token_ref", "") or "")
    code = _error_code(error)
    parts = [
        f"Route 53 failed for zone {zone.name}",
        f"pk {zone.pk}",
        f"hosted zone {hosted_zone_id(getattr(zone, 'provider_zone_id', ''))}",
        f"ref {ref}",
    ]
    if code:
        parts.append(f"code {code}")
    else:
        text = str(error)
        lowered = text.lower()
        if text and "access_key" not in lowered and "secret" not in lowered:
            parts.append(text)
    raise_alert(
        "r53-fail",
        f"dns_zone:{zone.name}",
        workspace=default_workspace(),
        fingerprint=f"r53-fail:{zone.pk}",
        source_engine="route53",
        title=f"Route 53 change failed for {zone.name}",
        body="; ".join(parts),
        fix_action="Check DnsZone.provider_zone_id and the Hub AWS credential ref",
    )


def observe_hosted_zone(client, zone):
    """GetHostedZone for DnsZone.provider_zone_id. Name/id judgment is the caller."""
    zid = hosted_zone_id(zone.provider_zone_id)
    if not zid:
        raise Route53Error("DnsZone has no provider_zone_id")
    try:
        resp = client.get_hosted_zone(Id=zid)
    except Exception as exc:
        raise Route53Error("GetHostedZone failed") from exc
    hosted = resp.get("HostedZone") or {}
    return {
        "id": hosted_zone_id(hosted.get("Id")),
        "name": _bare_name(hosted.get("Name")),
    }


def construct(zone):
    """Fail-closed Route 53 client for a DnsZone. Called from dns_provider_for."""
    from django.conf import settings

    from .aws_creds import AwsCredsError, load_credentials
    from .registry import ScopeError

    account = zone.account
    ref = str(account.dns_token_ref or "").strip()
    aws_ref = str(getattr(settings, "AWS_CREDENTIALS_REF", "") or "").strip()
    if not aws_ref:
        raise ScopeError(
            "AWS_CREDENTIALS_REF is empty; set HUB_AWS_CREDENTIALS_REF"
        )
    if not ref:
        raise ScopeError(
            f"DnsAccount {account.label!r} has no dns_token_ref; connect the "
            "account before constructing a client"
        )
    if ref != aws_ref:
        raise ScopeError(
            f"DnsAccount dns_token_ref {ref!r} must equal AWS_CREDENTIALS_REF"
        )
    try:
        creds = load_credentials(reason="route53 client construction")
    except AwsCredsError as error:
        file_r53_fail(zone, error)
        raise ScopeError(str(error)) from None
    client = boto3_client(
        "route53",
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
        region_name=DEFAULT_REGION,
    )
    try:
        observed = observe_hosted_zone(client, zone)
    except Route53Error as error:
        file_r53_fail(zone, error)
        raise ScopeError(str(error)) from None
    expected_name = _bare_name(zone.name)
    if observed["name"] != expected_name:
        error = Route53Error(
            f"hosted zone {observed['id']!r} is {observed['name']!r}, "
            f"expected {expected_name!r}"
        )
        file_r53_fail(zone, error)
        raise ScopeError(str(error)) from None
    expected_id = hosted_zone_id(zone.provider_zone_id)
    if observed["id"] and observed["id"] != expected_id:
        error = Route53Error(
            f"hosted zone id {observed['id']!r} != {expected_id!r}"
        )
        file_r53_fail(zone, error)
        raise ScopeError(str(error)) from None
    return Route53DnsProvider(zone, client=client)


class Route53DnsProvider(DnsProvider):
    """Route 53 client bound to one verified DnsZone. Not EdgeProtection."""

    def __init__(
        self,
        zone,
        *,
        client=None,
        access_key_id=None,
        secret_access_key=None,
        region_name=DEFAULT_REGION,
    ):
        if client is None:
            if not access_key_id or not secret_access_key:
                raise Route53Error(
                    "explicit AWS keys are required; refusing default chain"
                )
            client = boto3_client(
                "route53",
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                region_name=region_name,
            )
        self.zone = zone
        self._client = client

    def __repr__(self):
        return f"<Route53DnsProvider zone={self.zone.name!r}>"

    __str__ = __repr__

    def capabilities(self):
        return set()

    def list_records(self, zone):
        zone_id = self._zone_id(zone)
        rows = []
        kwargs = {"HostedZoneId": zone_id}
        while True:
            try:
                resp = self._client.list_resource_record_sets(**kwargs)
            except Exception as exc:
                self._fail(zone, exc)
            for rrs in resp.get("ResourceRecordSets") or []:
                name = str(rrs.get("Name") or "").rstrip(".")
                rtype = rrs.get("Type")
                values = [
                    item.get("Value")
                    for item in rrs.get("ResourceRecords") or []
                    if item.get("Value") is not None
                ]
                rows.append({
                    "id": _record_id(name, rtype, rrs.get("SetIdentifier")),
                    "name": name,
                    "rtype": rtype,
                    "values": values,
                    "proxied": False,
                    "ttl": rrs.get("TTL"),
                })
            if not resp.get("IsTruncated"):
                break
            kwargs = {
                "HostedZoneId": zone_id,
                "StartRecordName": resp["NextRecordName"],
                "StartRecordType": resp["NextRecordType"],
            }
            ident = resp.get("NextRecordIdentifier")
            if ident:
                kwargs["StartRecordIdentifier"] = ident
        return rows

    def upsert_record(self, zone, name, rtype, values, *, proxied=False, ttl=None):
        if proxied:
            raise Route53Error(
                "Route 53 does not support proxied records; refusing proxied=True "
                "(will not write an unproxied A)"
            )
        zone_id = self._zone_id(zone)
        wanted_ttl = int(ttl or DEFAULT_TTL)
        wanted = [str(value) for value in values]
        target = _bare_name(name)
        current = [
            rec for rec in self.list_records(zone)
            if _bare_name(rec["name"]) == target and rec["rtype"] == rtype
        ]
        if (
            len(current) == 1
            and sorted(current[0]["values"]) == sorted(wanted)
            and int(current[0].get("ttl") or 0) == wanted_ttl
        ):
            return current[0]["id"]
        try:
            self._client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={
                    "Changes": [{
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": _fqdn(name),
                            "Type": rtype,
                            "TTL": wanted_ttl,
                            "ResourceRecords": [{"Value": value} for value in wanted],
                        },
                    }],
                },
            )
        except Exception as exc:
            self._fail(zone, exc)
        return _record_id(name, rtype)

    def delete_record(self, zone, record_id):
        zone_id = self._zone_id(zone)
        current = [rec for rec in self.list_records(zone) if rec["id"] == record_id]
        if not current:
            return
        rec = current[0]
        try:
            self._client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={
                    "Changes": [{
                        "Action": "DELETE",
                        "ResourceRecordSet": {
                            "Name": _fqdn(rec["name"]),
                            "Type": rec["rtype"],
                            "TTL": int(rec.get("ttl") or DEFAULT_TTL),
                            "ResourceRecords": [
                                {"Value": value} for value in rec["values"]
                            ],
                        },
                    }],
                },
            )
        except ClientError as exc:
            if _error_code(exc) in {"NoSuchHostedZone", "InvalidChangeBatch"}:
                return
            self._fail(zone, exc)
        except Exception as exc:
            self._fail(zone, exc)

    def get_nameservers(self, domain):
        try:
            resp = self._client.get_hosted_zone(Id=self._zone_id(self.zone))
        except Exception as exc:
            self._fail(self.zone, exc)
        return list((resp.get("DelegationSet") or {}).get("NameServers") or [])

    def _zone_id(self, zone):
        if zone is not None and zone is not self.zone:
            same_row = (
                getattr(zone, "pk", None) is not None
                and getattr(zone, "pk", None) == self.zone.pk
            )
            if not same_row:
                raise Route53Error(
                    f"this client is bound to zone {self.zone.name!r}; "
                    f"refusing a call for a different zone"
                )
        zid = hosted_zone_id(self.zone.provider_zone_id)
        if not zid:
            raise Route53Error("DnsZone has no provider_zone_id")
        return zid

    def _fail(self, zone, exc):
        file_r53_fail(zone, exc)
        raise Route53Error("Route 53 request failed") from exc


@contextmanager
def mock_aws_route53():
    """T1 moto 5.x context. Dummy creds so boto3 never reaches live AWS."""
    from moto import mock_aws

    dummy = "testing"  # T1 dummy so boto3 cannot pick up a live profile
    pinned = {
        "AWS_ACCESS_KEY_ID": dummy,
        "AWS_SECRET_ACCESS_KEY": dummy,
        "AWS_SESSION_TOKEN": dummy,
        "AWS_SECURITY_TOKEN": dummy,
        "AWS_DEFAULT_REGION": DEFAULT_REGION,
        "AWS_REGION": DEFAULT_REGION,
    }
    saved = {name: os.environ.get(name) for name in pinned}
    os.environ.update(pinned)
    try:
        with mock_aws():
            yield
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def create_test_hosted_zone(name, *, caller_ref=None):
    """Allocate a hosted zone inside mock_aws_route53(). Dummy static creds."""
    dummy = "testing"
    client = boto3.client(
        "route53",
        region_name=DEFAULT_REGION,
        aws_access_key_id=dummy,
        aws_secret_access_key=dummy,
    )
    resp = client.create_hosted_zone(
        Name=_fqdn(name),
        CallerReference=caller_ref or f"hub-t1-{name}-{os.urandom(4).hex()}",
    )
    return hosted_zone_id(resp["HostedZone"]["Id"])
