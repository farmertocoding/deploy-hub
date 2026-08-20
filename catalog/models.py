"""Catalog application records (§D8).

Entries themselves land as dataclasses in a later task. This table is the
per-target memory of what was applied, so drift audit has a row to read.
"""
from django.db import models

from core.models import Target


class AppliedCatalogEntry(models.Model):
    """One catalog entry version applied to one Target."""

    target = models.ForeignKey(
        Target, on_delete=models.CASCADE, related_name="applied_catalog_entries",
    )
    entry_id = models.CharField(max_length=128)
    version = models.PositiveIntegerField()
    applied_at = models.DateTimeField(auto_now_add=True)
    mode = models.CharField(max_length=32)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target", "entry_id"],
                name="uniq_applied_catalog_target_entry",
            ),
        ]

    def __str__(self):
        return f"{self.target_id}:{self.entry_id}@{self.version}"
