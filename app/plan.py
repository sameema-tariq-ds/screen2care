# Clinical plan: the engine suggests, the clinician confirms or overrides with a reason.
import json
from datetime import date
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from app.database import engine
from app.rules import evaluate
from app.rules_runner import load_inputs

DISPOSITION_LABELS = {
    "RoutineRescreen": "Routine rescreening in 1–2 years",
    "ShortTermFollowUp": "Short-term diagnostic follow-up",
    "UrgentBiopsyReferral": "Urgent referral for tissue diagnosis (core needle biopsy / FNA)",
    "HighRiskSurveillance": "High-risk surveillance (annual imaging per protocol)",
}

LANE_TO_DISPOSITION = {
    "UrgentWorkup": "UrgentBiopsyReferral",
    "ShortInterval6M": "ShortTermFollowUp",
    "RecallBirads0": "ShortTermFollowUp",
    "RoutineScreening": "RoutineRescreen",
    "DenseSupplemental": "RoutineRescreen",
    "HighRisk-MRIOnly": "HighRiskSurveillance",
    "HighRisk-DBT+MRI": "HighRiskSurveillance",
    "HighRisk-DBT+ConsiderMRI": "HighRiskSurveillance",
}

DISPOSITION_TO_LANE = {
    "RoutineRescreen": "RoutineScreening",
    "ShortTermFollowUp": "ShortInterval6M",
    "UrgentBiopsyReferral": "UrgentWorkup",
    "HighRiskSurveillance": "HighRisk-DBT+ConsiderMRI",
}


class PlanIn(BaseModel):
    encounter_id: int
    disposition: Literal["RoutineRescreen", "ShortTermFollowUp", "UrgentBiopsyReferral", "HighRiskSurveillance"]
    followup_months: Optional[int] = Field(None, ge=1, le=24)
    override_reason: Optional[str] = Field(None, max_length=400)
    clinical_note: str = Field(min_length=3, max_length=5000)
    examiner_name: str = Field(min_length=2, max_length=150)
    signed_date: date

    @model_validator(mode="after")
    def followup_needs_months(self):
        if self.disposition == "ShortTermFollowUp" and not self.followup_months:
            raise ValueError("Enter the follow-up interval in months.")
        if self.disposition != "ShortTermFollowUp":
            self.followup_months = None
        return self


def _age(dob, on):
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _suggestion(conn, pid):
    d = evaluate(load_inputs(conn, pid))
    return {"lane": d.lane, "reason": d.reason, "flags": d.flags,
            "disposition": LANE_TO_DISPOSITION.get(d.lane)}


def get_plan_page(pid: str) -> dict:
    with engine.connect() as conn:
        patient = conn.execute(text(
            "SELECT patient_id, full_name, date_of_birth FROM patient WHERE patient_id = :p"), {"p": pid}
        ).mappings().first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        enc = conn.execute(text("""
            SELECT encounter_id, encounter_date, is_symptomatic, disposition, followup_months
            FROM encounter WHERE patient_id = :p ORDER BY encounter_date DESC, encounter_id DESC LIMIT 1
        """), {"p": pid}).mappings().first()
        imaging = conn.execute(text("""
            SELECT modality, laterality, birads_category, density, result_released_at
            FROM imaging_result WHERE patient_id = :p ORDER BY result_released_at DESC
        """), {"p": pid}).mappings().all()
        notes = conn.execute(text("""
            SELECT n.note_text, n.version_no, n.created_at, s.full_name AS author
            FROM clinical_note n
            JOIN encounter e ON e.encounter_id = n.encounter_id
            JOIN staff s ON s.staff_id = n.author_id
            WHERE e.patient_id = :p AND n.note_type = 'Clinical'
            ORDER BY n.created_at DESC
        """), {"p": pid}).mappings().all()
        current = conn.execute(text(
            "SELECT lane, reason, assigned_by FROM lane_assignment WHERE patient_id = :p AND is_current"),
            {"p": pid}).mappings().first()
        suggestion = _suggestion(conn, pid)
    return {"patient": patient, "enc": enc, "imaging": imaging, "notes": notes,
            "current": current, "suggestion": suggestion,
            "age": _age(patient["date_of_birth"], date.today())}


def save_plan(pid: str, data: PlanIn, clinician_id: int) -> dict:
    with engine.begin() as conn:
        enc_id = conn.execute(text(
            "SELECT encounter_id FROM encounter WHERE encounter_id = :e AND patient_id = :p"),
            {"e": data.encounter_id, "p": pid}).scalar()
        if enc_id is None:
            raise HTTPException(status_code=404, detail="Encounter not found for this patient")

        sugg = _suggestion(conn, pid)
        differs = sugg["disposition"] != data.disposition
        if differs and sugg["disposition"] and not (data.override_reason or "").strip():
            raise HTTPException(status_code=422,
                                detail="Give a reason: this differs from the engine suggestion.")

        prev = conn.execute(text("""
            SELECT note_id, version_no FROM clinical_note
            WHERE encounter_id = :e AND note_type = 'Clinical'
            ORDER BY version_no DESC LIMIT 1
        """), {"e": enc_id}).mappings().first()
        version = prev["version_no"] + 1 if prev else 1
        conn.execute(text("""
            INSERT INTO clinical_note (encounter_id, author_id, note_type, note_text, version_no, supersedes_note_id)
            VALUES (:e, :a, 'Clinical', :t, :v, :s)
        """), {"e": enc_id, "a": clinician_id, "t": data.clinical_note.strip(),
               "v": version, "s": prev["note_id"] if prev else None})

        conn.execute(text("""
            UPDATE encounter SET disposition = :d, followup_months = :f,
                   examiner_name = :x, signed_date = :s
            WHERE encounter_id = :e
        """), {"d": data.disposition, "f": data.followup_months, "x": data.examiner_name,
               "s": data.signed_date, "e": enc_id})

        # Lane: keep the engine's lane when the clinician confirms it, otherwise use the clinician's choice
        new_lane = DISPOSITION_TO_LANE[data.disposition] if differs else sugg["lane"]
        reason = (f"Clinician set: {DISPOSITION_LABELS[data.disposition]}" if differs
                  else f"{sugg['reason']} (confirmed by clinician)")
        override = (data.override_reason or "").strip() or (
            "Clinician decision; no engine suggestion yet" if differs else "Clinician confirmed engine suggestion")
        conn.execute(text("UPDATE lane_assignment SET is_current = FALSE WHERE patient_id = :p AND is_current"),
                     {"p": pid})
        conn.execute(text("""
            INSERT INTO lane_assignment (patient_id, lane, reason, assigned_by, clinician_id, override_reason)
            VALUES (:p, :lane, :reason, 'Clinician', :c, :o)
        """), {"p": pid, "lane": new_lane, "reason": reason, "c": clinician_id, "o": override})

        conn.execute(text("""
            INSERT INTO event_log (patient_id, event_type, actor_id, details)
            VALUES (:p, 'PlanSaved', :a, CAST(:d AS JSONB))
        """), {"p": pid, "a": clinician_id,
               "d": json.dumps({"encounter_id": enc_id, "disposition": data.disposition,
                                "overridden": differs, "note_version": version})})

    if new_lane == "UrgentWorkup":
        # The final clinical disposition explicitly authorizes the five-step
        # biopsy/oncology SLA timeline.
        from app.care_loop import open_episode
        with engine.begin() as conn:
            open_episode(conn, pid)

    return {"saved": True, "overridden": differs, "lane": new_lane, "note_version": version}


# ---------- Patient-facing note (optionally drafted by the local AI) -------------------

class ReleaseNoteIn(BaseModel):
    note_text: str = Field(min_length=10, max_length=3000)
    ai_drafted: bool = False


def note_source_text(pid: str) -> str:
    """What the AI rewrites: the latest clinical note plus the signed plan."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT e.disposition, e.followup_months,
                   (SELECT n.note_text FROM clinical_note n
                    WHERE n.encounter_id = e.encounter_id AND n.note_type IN ('Clinical','Disposition')
                      AND NOT n.is_released_to_patient
                    ORDER BY n.created_at DESC LIMIT 1) AS note_text
            FROM encounter e WHERE e.patient_id = :p
            ORDER BY e.encounter_date DESC, e.encounter_id DESC LIMIT 1
        """), {"p": pid}).mappings().first()
    if row is None or not (row["note_text"] or row["disposition"]):
        raise HTTPException(status_code=409, detail="Write and save the clinical note first.")
    parts = []
    if row["note_text"]:
        parts.append(f"Clinical note: {row['note_text']}")
    if row["disposition"]:
        plan = DISPOSITION_LABELS.get(row["disposition"], row["disposition"])
        if row["followup_months"]:
            plan += f" in {row['followup_months']} months"
        parts.append(f"Agreed plan: {plan}.")
    return "\n".join(parts)


def release_patient_note(pid: str, data: ReleaseNoteIn, staff_id: int) -> dict:
    with engine.begin() as conn:
        enc_id = conn.execute(text("""
            SELECT encounter_id FROM encounter WHERE patient_id = :p
            ORDER BY encounter_date DESC, encounter_id DESC LIMIT 1
        """), {"p": pid}).scalar()
        if enc_id is None:
            raise HTTPException(status_code=404, detail="No visit found for this patient")
        note_id = conn.execute(text("""
            INSERT INTO clinical_note (encounter_id, author_id, note_type, note_text,
                                       is_released_to_patient, released_at, released_by)
            VALUES (:e, :a, 'Clinical', :t, TRUE, now(), :a) RETURNING note_id
        """), {"e": enc_id, "a": staff_id, "t": data.note_text.strip()}).scalar()
        conn.execute(text("""
            INSERT INTO event_log (patient_id, event_type, actor_id, details)
            VALUES (:p, 'NoteReleasedToPatient', :a, CAST(:d AS JSONB))
        """), {"p": pid, "a": staff_id,
               "d": json.dumps({"note_id": note_id, "ai_drafted": data.ai_drafted})})
    return {"released": True, "note_id": note_id}
