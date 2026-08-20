"""Catalog application records (§D8).

Entries themselves land as dataclasses in a later task. This table is
append-only apply history: a row is written on every execution. Current
version is the latest applied_at for (target, entry_id). Same-version
re-apply is a probe-then-skip no-op in Task 5, not a unique constraint.
"""
from django.db import models

from core.models import Target


class AppliedCatalogEntry(models.Model):
    """One catalog execution on one Target. History stays; latest applied_at wins."""

    target = models.ForeignKey(
        Target, on_delete=models.CASCADE, related_name="applied_catalog_entries",
    )
    entry_id = models.CharField(max_length=128)
    version = models.PositiveIntegerField()
    applied_at = models.DateTimeField(auto_now_add=True)
    mode = models.CharField(max_length=32)
    result = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.target_id}:{self.entry_id}@{self.version}"
