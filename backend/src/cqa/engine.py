from decimal import ROUND_HALF_UP, Decimal

from .models import (
    Checklist,
    Conversation,
    CriterionResult,
    ModelResponse,
    ScoreResult,
    SectionResult,
)


class InvalidJudgments(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def validate_judgments(
    conversation: Conversation, checklist: Checklist, response: ModelResponse
) -> None:
    """Validate structure and evidence locations, NOT the truth of a semantic judgment."""
    problems: list[str] = []
    criteria = {c.id: c for c in checklist.criteria}
    messages = {m.message_id: m for m in conversation.transcript}
    positions = {m.message_id: i for i, m in enumerate(conversation.transcript)}
    first_operator = next(
        (m.message_id for m in conversation.transcript if m.speaker == "operator"), None
    )
    ids = [j.criterion_id for j in response.judgments]
    if len(ids) != len(set(ids)):
        problems.append("Duplicate criterion judgments")
    if set(ids) != set(criteria):
        problems.append("Judgments must cover exactly the selected checklist criteria")

    for judgment in response.judgments:
        criterion = criteria.get(judgment.criterion_id)
        if criterion is None:
            continue
        prefix = criterion.id + ": "
        if judgment.decision == "na":
            if not criterion.allow_na or not judgment.na_reason:
                problems.append(prefix + "N/A is not permitted or its explanation is missing")
        elif judgment.na_reason is not None:
            problems.append(prefix + "na_reason must be null for an applicable criterion")

        if judgment.decision == "score":
            if criterion.kind != "scale" or judgment.score not in [
                s.value for s in criterion.scale
            ]:
                problems.append(prefix + "Score is not an allowed scale level")
        elif judgment.score is not None:
            problems.append(prefix + "Only a scale decision can contain a score")
        if criterion.kind == "scale" and judgment.decision not in ("score", "na"):
            problems.append(prefix + "A scale requires a numeric decision")
        if criterion.kind != "scale" and judgment.decision not in ("yes", "no", "na"):
            problems.append(prefix + "A binary or flag criterion requires yes/no")

        evidence = judgment.evidence_message_ids
        if len(evidence) != len(set(evidence)):
            problems.append(prefix + "Duplicate evidence IDs")
        if any(mid not in messages for mid in evidence):
            problems.append(prefix + "Evidence references an unknown message")
        if not evidence and judgment.checked_range is None:
            problems.append(prefix + "Provide evidence or the checked conversation range")
        if judgment.checked_range is not None:
            start = positions.get(judgment.checked_range.start_message_id)
            end = positions.get(judgment.checked_range.end_message_id)
            if start is None or end is None or start > end:
                problems.append(prefix + "Invalid checked conversation range")

        positive = judgment.decision == "yes" or (
            judgment.decision == "score" and judgment.score is not None and judgment.score > 0
        )
        if positive:
            if not evidence:
                problems.append(prefix + "A positive judgment requires a supporting message")
            if criterion.evidence_policy == "operator" and not any(
                mid in messages and messages[mid].speaker == "operator" for mid in evidence
            ):
                problems.append(prefix + "Evidence must include an operator message")
            if criterion.evidence_policy == "first_operator" and first_operator not in evidence:
                problems.append(prefix + "Evidence must include the first operator response")
    if problems:
        raise InvalidJudgments(problems)


def rounded_score(earned: Decimal, applicable: Decimal) -> float | None:
    if not applicable:
        return None
    return float((100 * earned / applicable).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def evaluate(
    conversation: Conversation, checklist: Checklist, response: ModelResponse
) -> ScoreResult:
    validate_judgments(conversation, checklist, response)
    judgments = {j.criterion_id: j for j in response.judgments}
    messages = {m.message_id: m for m in conversation.transcript}
    denominator = sum(
        (
            Decimal(str(c.weight))
            for c in checklist.criteria
            if c.kind != "flag" and judgments[c.id].decision != "na"
        ),
        Decimal(0),
    )
    earned_total = Decimal(0)
    results: list[CriterionResult] = []
    section_totals: dict[str, tuple[Decimal, Decimal]] = {}
    for criterion in checklist.criteria:
        judgment = judgments[criterion.id]
        weight = Decimal(str(criterion.weight))
        applicable = criterion.kind != "flag" and judgment.decision != "na"
        earned = Decimal(0)
        if applicable:
            if criterion.kind == "binary":
                ratio = Decimal(1 if judgment.decision == "yes" else 0)
            else:
                ratio = Decimal(str(judgment.score)) / Decimal(
                    str(max(s.value for s in criterion.scale))
                )
            earned = weight * ratio
            earned_total += earned
        if criterion.kind != "flag":
            section_weight, section_earned = section_totals.get(
                criterion.section, (Decimal(0), Decimal(0))
            )
            section_totals[criterion.section] = (
                section_weight + (weight if applicable else Decimal(0)),
                section_earned + earned,
            )
        results.append(
            CriterionResult(
                criterion_id=criterion.id,
                title=criterion.title,
                section=criterion.section,
                kind=criterion.kind,
                judgment=judgment,
                evidence=[messages[mid] for mid in judgment.evidence_message_ids],
                weight=float(weight),
                effective_weight=float(100 * weight / denominator)
                if applicable and denominator
                else 0,
                earned_weight=float(earned) if applicable else None,
                contribution=float(100 * earned / denominator)
                if applicable and denominator
                else None,
                flagged=criterion.kind == "flag" and judgment.decision == "yes",
            )
        )
    return ScoreResult(
        total_score=rounded_score(earned_total, denominator),
        applicable_weight=float(denominator),
        earned_weight=float(earned_total),
        flagged_criteria=[r.criterion_id for r in results if r.flagged],
        criteria=results,
        sections=[
            SectionResult(
                section=section,
                applicable_weight=float(weight),
                earned_weight=float(earned),
                score=rounded_score(earned, weight),
            )
            for section, (weight, earned) in section_totals.items()
        ],
    )
