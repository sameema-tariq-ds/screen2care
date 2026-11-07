"""Pure screening assessment rules. This module has no web or database dependency."""

from dataclasses import dataclass

from app.checks import collect_warnings
from app.rules_config import (
    HIGH_RISK_RADIATION_MAX_AGE,
    RECALL_BIRADS,
    RULES_VERSION,
    SHORT_INTERVAL_BIRADS,
    URGENT_BIRADS,
)
from app.schemas import ExamStatus, GeneticStatus, HighRiskBiopsy, IntakeForm, YesNoUnknown


@dataclass(frozen=True)
class Assessment:
    tier: str
    actionable: bool
    urgency: str
    reasons: tuple[str, ...]
    missing: tuple[str, ...]
    rules_version: str = RULES_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "actionable": self.actionable,
            "urgency": self.urgency,
            "reasons": list(self.reasons),
            "missing": list(self.missing),
            "rules_version": self.rules_version,
        }


def assess(form: IntakeForm) -> Assessment:
    reasons: list[str] = []
    missing: list[str] = []
    scans = sorted(form.imaging, key=lambda item: item.date, reverse=True)
    latest = scans[0] if scans else None
    abnormal_exam = any(
        item.inspection == ExamStatus.ABNORMAL
        or item.mass == ExamStatus.ABNORMAL
        or item.axillary_nodes == ExamStatus.ABNORMAL
        for item in (form.cbe_right, form.cbe_left)
    )

    if form.presentation is True or abnormal_exam:
        reasons.append("Diagnostic presentation or abnormal examination.")
        return Assessment("Diagnostic", True, "Urgent" if abnormal_exam else "Priority", tuple(reasons), ())

    if latest is None:
        missing.append("Imaging")
        return Assessment("Incomplete intake", True, "Pending", ("No imaging has been recorded yet.",), tuple(missing))

    if latest.birads in URGENT_BIRADS:
        return Assessment("Urgent biopsy", True, "Urgent", (f"Latest BI-RADS is {latest.birads}.",), ())
    if latest.birads == RECALL_BIRADS:
        return Assessment("Imaging recall", True, "Priority", ("BI-RADS 0 requires additional imaging.",), ())
    if latest.birads == SHORT_INTERVAL_BIRADS:
        return Assessment("Short-term follow-up", True, "Priority", ("BI-RADS 3 requires short-term follow-up.",), ())

    high_risk = form.genetic_status == GeneticStatus.POSITIVE or form.high_risk_biopsy in {
        HighRiskBiopsy.ADH,
        HighRiskBiopsy.ALH,
        HighRiskBiopsy.LCIS,
    } or (
        form.chest_radiation == YesNoUnknown.YES
        and form.chest_radiation_age is not None
        and form.chest_radiation_age <= HIGH_RISK_RADIATION_MAX_AGE
    )
    if high_risk:
        reasons.append("One or more high-risk inputs meet the surveillance threshold.")
        return Assessment("High-risk surveillance", True, "Priority", tuple(reasons), ())

    if latest.birads in {1, 2}:
        return Assessment("Routine screening", False, "Routine", (f"Latest BI-RADS is {latest.birads}.",), ())
    warnings = collect_warnings(form)
    return Assessment("Clinical review", True, "Priority", tuple(warnings) or ("Manual clinical review required.",), ())

