"""First-visit risk tier shown after an intake is saved.

Ported from screen2care (src/risk_engine.py, branch feature/screening). It reads the
saved form snapshot only, and does not calculate a lifetime-risk percentage; the Low
label says so. Routing into lanes and the care loop stays with app/rules.py.
"""
from dataclasses import dataclass
from typing import Any

from app.schemas import PlanOption

RULES_VERSION = "risk-first-visit-2026-11-08.v1"
HIGH_GENES = {"BRCA1", "BRCA2", "TP53", "PTEN"}
HIGH_BIOPSIES = {"ADH", "ALH", "LCIS"}
ALERT_TRIGGERS = {
    "High": "CRITICAL HIGH-RISK CARE ROUTING ACTIVE",
    "Medium": "DENSE TISSUE MASKING RISK / SHORT-INTERVAL TRACKING",
    "Low": "ROUTINE SCREENING ELIGIBLE",
    "Baseline": "FIRST SCREENING BASELINE",
}


@dataclass(frozen=True)
class RiskAssessment:
    tier: str
    label: str
    reasons: tuple[str, ...]
    rules_version: str = RULES_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "label": self.label, "alert_trigger": ALERT_TRIGGERS[self.tier],
                "reasons": list(self.reasons), "rules_version": self.rules_version}


def calculate_risk(form: dict[str, Any]) -> RiskAssessment:
    """form: the submitted payload as saved in encounter_snapshot (plus 'age')."""
    reasons: list[str] = []

    gene = form.get("genetic_gene_other") if form.get("genetic_gene") == "Other" else form.get("genetic_gene")
    if form.get("genetic_status") == "Positive" and gene in HIGH_GENES:
        reasons.append(f"Positive genetic test ({gene}).")

    rad_age = form.get("chest_radiation_age")
    if form.get("chest_radiation") == "Yes" and rad_age is not None and 10 <= rad_age <= 30:
        reasons.append(f"Chest radiation at age {rad_age} (between 10 and 30).")

    if form.get("high_risk_biopsy") in HIGH_BIOPSIES:
        reasons.append(f"High-risk biopsy finding: {form['high_risk_biopsy']}.")
    for entry in form.get("breast_history") or []:
        details = str(entry.get("details") or "").upper()
        if entry.get("type") == "Biopsy" and any(m in details for m in HIGH_BIOPSIES):
            reasons.append(f"Previous biopsy: {entry.get('details')}.")
            break

    for rel in form.get("family_history") or []:
        if (str(rel.get("relation", "")).strip().lower() in {"mother", "sister"}
                and rel.get("cancer_type") == "Breast" and (rel.get("age_at_diagnosis") or 120) < 50):
            reasons.append(f"{rel['relation']} had breast cancer at age {rel['age_at_diagnosis']}.")
        if rel.get("known_genetic_mutations") in ("BRCA1", "BRCA2"):
            reasons.append(f"{rel['relation']} carries a {rel['known_genetic_mutations']} mutation.")

    scans = sorted((s for s in form.get("imaging") or [] if s.get("modality") in ("Mammogram", "DBT")),
                   key=lambda s: s.get("date", ""), reverse=True)
    latest = scans[0] if scans else None
    medium: list[str] = []
    if latest and latest.get("density") in ("C", "D"):
        medium.append(f"Dense breast tissue (density {latest['density']}, {latest['modality']}).")
    if any(s.get("birads") == 3 for s in scans):
        medium.append("BI-RADS 3 (probably benign): short-interval follow-up.")

    if reasons:
        return RiskAssessment("High", "High", tuple(reasons))
    if medium:
        return RiskAssessment("Medium", "Medium", tuple(medium))
    if not scans:
        return RiskAssessment("Baseline", "Baseline assessment",
                              ("No mammogram or DBT baseline recorded yet; continue symptom-based or clinician-directed care.",))
    age = form.get("age")
    if latest.get("density") in ("A", "B") and latest.get("birads") in (1, 2):
        return RiskAssessment("Low", "Low (lifetime risk not assessed)",
                              (f"Age {age}; density {latest['density']}; BI-RADS {latest['birads']}.",))
    return RiskAssessment("Low", "Low (lifetime risk not assessed)", (f"Age {age}; no high or medium triggers.",))


def plan_disposition(plan: list[str]) -> str | None:
    """Map the chosen plan options to the encounter disposition used by the care loop."""
    if PlanOption.URGENT_BIOPSY in plan:
        return "UrgentBiopsyReferral"
    if PlanOption.SHORT_TERM_FOLLOW_UP in plan:
        return "ShortTermFollowUp"
    if PlanOption.ANNUAL_DBT_MRI_6M in plan or PlanOption.ANNUAL_MRI in plan:
        return "HighRiskSurveillance"
    if PlanOption.ROUTINE_RESCREEN in plan:
        return "RoutineRescreen"
    return None   # wellness tracking, genetics referral or stop screening: no screening disposition
