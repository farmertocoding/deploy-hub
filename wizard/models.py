"""Wizard answers: one row per question, never one JSON blob.

§D3 set the precedent ("desired state is relational — the JSON blob is dropped") and
the reasons apply here too: per-field audit, partial save that survives a browser
close, and a unique constraint that makes "answered twice" impossible rather than
last-write-wins.

Secret answers store a vault reference, never a value. There is no code path that
writes an answer value into this table for a question of kind=secret — enforced by
`set_answer()` being the only writer and by a test that tries the bypass.
"""
from django.conf import settings
from django.db import models

from core.models import Site


class WizardAnswer(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="answers")
    question_id = models.CharField(max_length=128)

    # Exactly one of these carries the answer. `secret_ref` is a POINTER to a vault
    # row, never a value — the name says so because `answer.secret` read like the
    # secret itself at every call site.
    value = models.JSONField(null=True, blank=True)
    secret_ref = models.ForeignKey("vault.Secret", null=True, blank=True,
                               on_delete=models.PROTECT, related_name="+")
    is_secret = models.BooleanField(default=False)

    answered_at = models.DateTimeField(auto_now=True)
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "question_id"],
                                    name="uniq_answer_site_question"),
            # A secret answer with a plaintext value, or a secret answer with no
            # vault row, are both bugs the database itself should refuse.
            models.CheckConstraint(
                condition=(
                    models.Q(is_secret=False, secret_ref__isnull=True)
                    | models.Q(is_secret=True, value__isnull=True,
                               secret_ref__isnull=False)
                ),
                name="answer_secret_xor_value",
            ),
        ]

    def __str__(self):
        return f"{self.site_id}:{self.question_id}" + (" (secret)" if self.is_secret else "")

    def __repr__(self):
        return f"<WizardAnswer {self.question_id} {'secret' if self.is_secret else 'plain'}>"
