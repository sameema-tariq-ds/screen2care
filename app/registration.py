# Front-desk registration (Admin). The Admin records who the patient is and which
# clinician will see them; nothing clinical. The clinician then completes the clinical
# proforma, including the imaging report and BI-RADS (app/intake.py).
import json
from datetime import date
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from app.database import engine


class RegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=150)
    date_of_birth: date
    patient_id: str = Field(..., pattern=r"^BC-([A-Z]{2}-\d{3}|\d{5})$")
    phone: str = Field(min_length=7, max_length=30)
    national_id: str = Field(..., min_length=15, max_length=15,
                             pattern=r"^\d{5}-\d{7}-\d$")
    clinician_staff_id: int
    update_existing: bool = False    # True only after the desk loaded the record with "Find existing patient"

    @model_validator(mode="after")
    def check(self):
        self.full_name = self.full_name.strip()
        self.patient_id = self.patient_id.strip().upper()
        self.national_id = self.national_id.strip()
        if self.date_of_birth >= date.today():
            raise ValueError("Date of birth must be in the past.")
        return self


def active_clinicians() -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT staff_id, full_name FROM staff WHERE role = 'Clinician' AND is_active ORDER BY full_name
        """)).mappings()]


def find_patient(conn, patient_id: str | None, national_id: str | None) -> tuple[str | None, bool]:
    """Existing patient by Patient ID, else by national ID. Returns (patient_id, exists)."""
    by_nid = None
    if national_id:
        by_nid = conn.execute(text("SELECT patient_id FROM patient WHERE national_id = :n"),
                              {"n": national_id}).scalar()
    if patient_id:
        exists = conn.execute(text("SELECT 1 FROM patient WHERE patient_id = :p"), {"p": patient_id}).first()
        if by_nid and by_nid != patient_id:
            raise HTTPException(status_code=409,
                                detail=f"National ID {national_id} is already registered with patient {by_nid}.")
        return patient_id, exists is not None
    return by_nid, by_nid is not None


def register_patient(r: RegistrationIn, admin_staff_id: int | None) -> dict:
    with engine.begin() as conn:
        clinician = conn.execute(text("""
            SELECT full_name FROM staff WHERE staff_id = :s AND role = 'Clinician' AND is_active
        """), {"s": r.clinician_staff_id}).scalar()
        if clinician is None:
            raise HTTPException(status_code=422, detail="Choose an active clinician for this patient.")

        patient_id, returning = find_patient(conn, r.patient_id, r.national_id)
        if returning and not r.update_existing:
            name = conn.execute(text("SELECT full_name FROM patient WHERE patient_id = :p"), {"p": patient_id}).scalar()
            raise HTTPException(status_code=409, detail=(
                                f"Patient ID {patient_id} is already registered with {name}. To check in this patient, use "
                                "'Find existing patient' first."))
        params = {"n": r.full_name, "d": r.date_of_birth, "nid": r.national_id, "ph": r.phone, "by": admin_staff_id}
        if returning:
            conn.execute(text("""
                UPDATE patient SET full_name = :n, date_of_birth = :d, phone = :ph,
                       national_id = COALESCE(:nid, national_id)
                WHERE patient_id = :p
            """), {**params, "p": patient_id})
        else:
            conn.execute(text("""
                INSERT INTO patient (patient_id, full_name, date_of_birth, national_id, phone, created_by)
                VALUES (:p, :n, :d, :nid, :ph, :by)
            """), {**params, "p": patient_id})

        conn.execute(text("""
            INSERT INTO care_team_assignment (patient_id, staff_id, assigned_by) VALUES (:p, :s, :by)
            ON CONFLICT DO NOTHING
        """), {"p": patient_id, "s": r.clinician_staff_id, "by": admin_staff_id})
        conn.execute(text("""
            INSERT INTO event_log (patient_id, event_type, actor_id, details)
            VALUES (:p, 'PatientRegistered', :by, CAST(:d AS JSONB))
        """), {"p": patient_id, "by": admin_staff_id, "d": json.dumps(
            {"returning_patient": returning, "clinician_staff_id": r.clinician_staff_id})})

    return {"patient_id": patient_id, "returning_patient": returning, "clinician": clinician}


def lookup_registration(patient_id: str) -> dict:
    """Demographics and assigned clinicians only: the front desk does not see clinical data."""
    with engine.connect() as conn:
        patient = conn.execute(text("""
            SELECT patient_id, full_name, date_of_birth, phone, national_id FROM patient WHERE patient_id = :p
        """), {"p": patient_id.strip().upper()}).mappings().first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Record not found.")
        team = conn.execute(text("""
            SELECT s.staff_id, s.full_name FROM care_team_assignment c JOIN staff s USING (staff_id)
            WHERE c.patient_id = :p AND s.role = 'Clinician' ORDER BY c.assigned_at
        """), {"p": patient["patient_id"]}).mappings().all()
    return {"patient": {**patient, "date_of_birth": patient["date_of_birth"].isoformat()},
            "clinicians": [dict(t) for t in team]}


def waiting_for_intake(staff_id: int | None) -> list[dict]:
    """This clinician's patients registered at the front desk since their last clinical intake."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT p.patient_id, p.full_name, date_part('year', age(p.date_of_birth))::int AS age, reg.at AS registered_at
            FROM care_team_assignment c
            JOIN patient p ON p.patient_id = c.patient_id
            JOIN LATERAL (SELECT MAX(event_at) AS at FROM event_log
                          WHERE patient_id = p.patient_id AND event_type = 'PatientRegistered') reg ON reg.at IS NOT NULL
            WHERE c.staff_id = :s
              AND NOT EXISTS (SELECT 1 FROM event_log i WHERE i.patient_id = p.patient_id
                                AND i.event_type = 'IntakeSubmitted' AND i.event_at >= reg.at)
            ORDER BY reg.at
        """), {"s": staff_id}).mappings()]
