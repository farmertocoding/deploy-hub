from django.utils import timezone

from core.hud.operations import OperationDispatchError
from core.models import Project


def scan_project(operation):
    from scanner.core import scan
    from wizard.materialize import report_hash

    project = Project.objects.get(pk=operation.object_id, workspace=operation.workspace)
    if project.source_kind != Project.Source.LOCAL_PATH or not project.local_path:
        raise OperationDispatchError(
            "A checked-out local source is required for an asynchronous scan.",
            code="source_unavailable",
        )
    from core.local_sources import LocalSourceError, resolve_local_source

    try:
        source = resolve_local_source(
            project.local_path, require_root=True,
        )
    except LocalSourceError as exc:
        raise OperationDispatchError(str(exc), code="source_unavailable") from exc
    report = scan(str(source))
    project.scan_report = report
    project.scanned_at = timezone.now()
    project.scan_source_fingerprint = report_hash(report)
    project.save(update_fields=["scan_report", "scanned_at", "scan_source_fingerprint"])
    return {
        "ok": True, "project_id": project.pk,
        "scan_report_hash": project.scan_source_fingerprint,
    }
