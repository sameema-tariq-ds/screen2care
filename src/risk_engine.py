"""Deterministic first-visit breast-screening risk rules.

The calculator consumes the immutable submitted snapshot, not mutable form state.
It intentionally does not calculate a lifetime percentage; the low label makes
that limitation explicit to the clinician.
"""

from dataclasses import dataclass
from typing import Any

RULES_VERSION = "risk-first-visit-2026-11-08.v1"
HIGH_GENES = {"BRCA1", "BRCA2", "TP53", "PTEN"}
HIGH_BIOPSIES = {"ADH", "ALH", "LCIS", "ADH/LCIS", "Cancer"}
ALERT_TRIGGERS = {
    "High": "CRITICAL HIGH-RISK CARE ROUTING ACTIVE",
    "Medium": "DENSE TISSUE MASKING RISK / SHORT-INTERVAL TRACKING",
    "Low": "ROUTINE SCREENING ELIGIBLE",
    "Incomplete": "RISK ASSESSMENT PENDING",
}


@dataclass(frozen=True)
class RiskAssessment:
    tier: str
    label: str
    reasons: tuple[str, ...]
    rules_version: str = RULES_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "label": self.label,
            "alert_trigger": ALERT_TRIGGERS[self.tier],
            "reasons": list(self.reasons),
            "rules_version": self.rules_version,
        }


def _submitted(snapshot: dict[str, Any]) -> dict[str, Any]:
    return snapshot.get("submitted", snapshot)


def _scan_is_mammogram(scan: dict[str, Any]) -> bool:
    return scan.get("modality") in {"Mammogram", "DBT"}


def calculate_risk(snapshot: dict[str, Any]) -> RiskAssessment:
    """Calculate risk using only normalized values in a saved intake snapshot."""
    data = _submitted(snapshot)
    reasons: list[str] = []

    gene_status = data.get("genetic_status")
    gene = data.get("genetic_gene")
    if gene_status == "Positive" and gene in HIGH_GENES:
        reasons.append(f"genetic_status = Positive ({gene}).")

    radiation_age = data.get("chest_radiation_age")
    if data.get("chest_radiation") == "Yes" and radiation_age is not None and 10 <= radiation_age <= 30:
        reasons.append(f"chest_radiation = Yes; chest_radiation_age = {radiation_age}.")

    if data.get("high_risk_biopsy") in HIGH_BIOPSIES:
        reasons.append(f"high_risk_biopsy = {data['high_risk_biopsy']}.")
    for biopsy in data.get("biopsy_history", []):
        if biopsy.get("result") in HIGH_BIOPSIES:
            reasons.append(f"biopsy_history.result = {biopsy['result']}.")
            break

    for relative in data.get("family_history", []):
        relation = str(relative.get("relation", "")).strip().lower()
        if (
            relation in {"mother", "sister"}
            and relative.get("cancer_type") == "Breast"
            and relative.get("age_at_diagnosis", 120) < 50
        ):
            reasons.append(
                "family_history = "
                f"{relative.get('relation')} breast cancer at age {relative.get('age_at_diagnosis')}."
            )

    scans = [scan for scan in data.get("imaging", []) if _scan_is_mammogram(scan)]
    scans.sort(key=lambda scan: scan.get("date", ""), reverse=True)
    latest = scans[0] if scans else None
    medium_reasons: list[str] = []
    if latest and latest.get("density") in {"C", "D"}:
        medium_reasons.append(f"imaging.density = {latest['density']} ({latest.get('modality')}).")
    if any(scan.get("birads") == 3 for scan in scans):
        medium_reasons.append("imaging.birads = 3 (probably benign; short-interval follow-up).")

    if reasons:
        return RiskAssessment("High", "High", tuple(reasons))
    if medium_reasons:
        return RiskAssessment("Medium", "Medium", tuple(medium_reasons))

    age = data.get("age")
    if not scans or data.get("imaging_not_done"):
        return RiskAssessment("Incomplete", "Incomplete", ("Imaging is not available for risk assessment.",))
    if latest and latest.get("density") in {"A", "B"} and latest.get("birads") in {1, 2}:
        return RiskAssessment(
            "Low", "Low (lifetime risk not assessed)",
            (f"age = {age}; mammogram density = {latest['density']}; BI-RADS = {latest['birads']}.",),
        )
    return RiskAssessment("Low", "Low (lifetime risk not assessed)", (f"age = {age}; no high or medium triggers.",))
