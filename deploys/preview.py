"""Private-repo preview sibling Site. Does not deploy."""
import re

from core.models import Project, Site

_REF_SLUG = re.compile(r"[^a-zA-Z0-9._-]+")


class PreviewError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def create_preview(parent, ref, *, visibility=None):
    if not isinstance(ref, str) or not ref.strip() or len(ref) > 128:
        raise PreviewError("invalid ref")
    if visibility is None:
        raise PreviewError("visibility refused")
    if visibility == "public":
        raise PreviewError("public repo refused")
    project = parent.project
    if project.source_kind != Project.Source.GIT or not project.git_url:
        raise PreviewError("not a git project")
    if visibility != "private":
        raise PreviewError("visibility refused")
    slug = _REF_SLUG.sub("-", ref).strip("-")[:80] or "ref"
    name = f"preview-{parent.name}-{slug}"
    return Site.objects.create(
        project=project,
        name=name,
        exposure=Site.Exposure.MESH_ONLY,
        preview_of=parent,
        preview_ref=ref,
        primary_target=parent.primary_target,
        dns_zone=None,
    )
