from core.hud.operations import OperationDispatchError
from core.models import Target
from core.ssh import SshTransport


def probe_target(operation):
    from monitor.collector import collect

    try:
        target = Target.objects.get(pk=operation.object_id, zone__workspace=operation.workspace)
    except Target.DoesNotExist as exc:
        raise OperationDispatchError(
            "Target not found in this workspace.", code="not_found",
        ) from exc
    payload = collect(target, SshTransport(target), sleep=lambda _seconds: None)
    return {"ok": True, "target_id": target.pk, "observed_at": payload.get("ts")}
