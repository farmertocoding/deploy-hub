"""Question assembly + answer validation.

The wizard is SERVER-DRIVEN: the client renders whatever question list this module
returns and holds no copy of the logic. A client-side duplicate would drift within a
phase, and the drift would show up as a manifest built from questions nobody asked.

Error-proofing is the whole job of this module (Joseph's stated priority). Every
answer is checked against the question that produced it — kind, choices, emptiness —
before it can reach the vault or a manifest. Unknown question ids are rejected rather
than ignored, because silently dropping an answer is how a site deploys with a
half-configured env and nobody finds out until it 500s.
"""
from django.core.exceptions import ValidationError

from scanner.core import WizardQuestion

# Canonical questions the wizard always asks (master plan §5.2). Modules ask their own
# framework-specific ones on top.
BASE_QUESTIONS = [
    WizardQuestion(id="site.domain", kind="text",
                   prompt="Public domain for this site (e.g. app.example.com)"),
    WizardQuestion(id="site.exposure", kind="choice", default="public",
                   choices=["public", "mesh_only"],
                   prompt="How should this site be reachable?"),
]

# Modules ask for the same things under their own namespaces. Collapsing them here
# keeps the UI from asking for the domain twice; the alias map stays small and
# explicit rather than becoming a guessing heuristic on question text.
ALIASES = {
    "django.domain": "site.domain",
    "django.exposure": "site.exposure",
    "node_ts.domain": "site.domain",
    "node_ts.exposure": "site.exposure",
}

REQUIRED_IDS = {"site.domain"}


class UnknownQuestion(ValidationError):
    pass


def question_set(project):
    """Canonical base questions + module questions, de-duplicated and aliased.

    Order is stable (base first, then modules in scan order) so the UI doesn't
    reshuffle between polls — a moving form is a form people mis-answer.
    """
    report = project.scan_report or {}
    questions = list(BASE_QUESTIONS)
    seen = {q.id for q in questions}

    for raw in report.get("wizard_questions", []):
        qid = ALIASES.get(raw["id"], raw["id"])
        if qid in seen:
            continue
        seen.add(qid)
        questions.append(WizardQuestion(
            id=qid,
            prompt=raw.get("prompt", qid),
            kind=raw.get("kind", "text"),
            default=raw.get("default"),
            choices=raw.get("choices") or [],
        ))
    return questions


def question_map(project):
    return {q.id: q for q in question_set(project)}


def coerce_answer(question, value):
    """Validate one answer against its question. Raises ValidationError with a code.

    Deliberately strict about types. 'true' and True are the same intent, but 'yes'
    and 'sure' are not — a wizard that guesses produces a manifest nobody predicted.
    """
    kind = question.kind

    if value is None:
        raise ValidationError("an answer is required", code="required")

    if kind == "secret":
        if not isinstance(value, str) or not value:
            raise ValidationError("a secret value must be a non-empty string",
                                  code="invalid")
        return value

    if kind == "text":
        if not isinstance(value, str):
            raise ValidationError("expected text", code="invalid")
        value = value.strip()
        if not value:
            raise ValidationError("an answer is required", code="required")
        if len(value) > 2048:
            raise ValidationError("answer is too long", code="too_long")
        return value

    if kind == "choice":
        if value not in question.choices:
            raise ValidationError(
                f"{value!r} is not one of: {', '.join(map(str, question.choices))}",
                code="invalid_choice")
        return value

    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValidationError("expected true or false", code="invalid")

    if kind == "number":
        if isinstance(value, bool):   # bool is an int subclass; not a number here
            raise ValidationError("expected a number", code="invalid")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                raise ValidationError("expected a number", code="invalid") from None
        raise ValidationError("expected a number", code="invalid")

    raise ValidationError(f"unsupported question kind {kind!r}", code="invalid")


def validate_answers(project, incoming: dict):
    """Validate a partial answer set. Returns {question_id: (question, coerced)}.

    All-or-nothing: one bad field rejects the whole PATCH, so the client never ends up
    with half its answers persisted and no clear signal about which half.
    """
    known = question_map(project)
    errors, cleaned = {}, {}

    for qid, value in incoming.items():
        question = known.get(qid)
        if question is None:
            errors[qid] = ["no such question for this project", "unknown_question"]
            continue
        try:
            cleaned[qid] = (question, coerce_answer(question, value))
        except ValidationError as exc:
            errors[qid] = [exc.message, exc.code]

    if errors:
        raise ValidationError({k: [v[0]] for k, v in errors.items()})
    return cleaned


def missing_required(project, answered_ids):
    """Required questions still unanswered. Domain is required; module questions are
    advisory in v1 because a module cannot know which of its env vars the operator
    intends to supply at the target instead."""
    return sorted(REQUIRED_IDS - set(answered_ids))
