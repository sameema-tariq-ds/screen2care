"""Small, serialisable contract for handing an assessed case to another worker."""

from dataclasses import dataclass

from app.assess import Assessment


@dataclass(frozen=True)
class Handover:
    patient_id: str
    encounter_id: int
    tier: str
    actionable: bool
    urgency: str
    reasons: tuple[str, ...]
    missing: tuple[str, ...]
    rules_version: str


def make_handover(patient_id: str, encounter_id: int, assessment: Assessment) -> Handover:
    return Handover(patient_id, encounter_id, assessment.tier, assessment.actionable, assessment.urgency,
                    assessment.reasons, assessment.missing, assessment.rules_version)

