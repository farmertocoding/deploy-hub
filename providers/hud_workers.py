from core.hud.operations import OperationDispatchError
from core.models import DnsAccount


def verify_integration(operation):
    action = operation.action
    if action in ("cloudflare.verify", "dns.verify", "integration.verify"):
        account = DnsAccount.objects.filter(
            workspace=operation.workspace, provider="cloudflare",
        ).order_by("pk").first()
        if account and account.dns_token_ref:
            from providers.cloudflare import verify_token

            observed = verify_token(account.dns_token_ref)
            return {
                "ok": True, "provider": "cloudflare",
                "status": observed.get("status", "verified"),
            }
        if action == "cloudflare.verify":
            raise OperationDispatchError(
                "Cloudflare credential reference is missing.", code="credential_ref_missing",
            )
    if action in ("aws.verify", "integration.verify"):
        from providers.aws_creds import audit_iam_scope

        run = audit_iam_scope()
        return {"ok": True, "provider": "aws", "status": run.status}
    raise OperationDispatchError(
        "No verifiable integration is configured.", code="integration_missing",
    )
