# The screening-to-care loop: every step that starts or stops an SLA clock, and the
# breach checker that routes an alert to the right role.
#
#   S1  result released (BI-RADS 4/5) -> patient acknowledges        24 h  -> Navigator
#   S2  patient acknowledges          -> biopsy booked               7 d   -> Scheduling Manager
#   S3  biopsy performed              -> pathology report            5 d   -> Lab Director
#   S4  malignant confirmed           -> oncology referral assigned  5 d   -> Tumor Board
#   S5  malignant confirmed           -> treatment started           21 d  -> CMO (red flag)
#
# Target hours and the escalation role come from the sla_definition table.
# SMS and phone calls are recorded in patient_contact; nothing is actually sent yet.
import json
from datetime import datetime
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import engine

ALERT_ACTIONS = {
    1: "No reply to the result SMS within 24 hours. Start the backup phone call now.",
    2: "No biopsy booked 7 days after the patient acknowledged. Clear the waitlist and open an emergency slot.",
    3: "No pathology report 5 days after the biopsy. Find the delayed sample.",
    4: "Oncology referral still unassigned 5 days after the malignant result. Review the full profile and assign now.",
    5: "RED FLAG: no treatment started 21 days after the malignant result. Immediate administrative action needed.",
}

# The surgical and oncology team that gets a heads-up when a BI-RADS 4/5 loop opens
ONCOLOGY_TEAM_ROLE = "TumorBoard"

# Which roles may do each step (enforced in the API and used to show the right buttons)
STEP_ROLES = {
    "contact": ("Navigator", "Clinician"),
    "book_biopsy": ("Navigator", "SchedulingManager"),  # date and time of the biopsy appointment
    "biopsy_performed": ("Radiologist",),
    "pathology": ("Pathologist",),
    "assign_referral": ("Navigator",),             # navigator refers a malignant result to an oncologist
    "treatment": ("Clinician",),
    "book_results": ("Clinician", "Navigator"),     # appointment to go through the biopsy result
    "disclose_result": ("Clinician",),              # only a doctor tells the patient the result
    "close_loop": ("CMO", "Navigator", "Clinician"),  # which reasons each may use: CLOSE_REASONS
    "reopen_loop": ("CMO", "Clinician"),
}

# Closing a loop without treatment. The loop is never deleted: clocks stop, alerts are
# resolved and the record stays, so the CMO can review it and the loop can be reopened.
CLOSE_REASONS = {
    "LostToFollowUp": ("CMO", "Navigator"),
    "Transferred": ("CMO", "Navigator"),
    "Deceased": ("CMO", "Navigator"),
    "Declined": ("Clinician",),               # a doctor explains the risk before a refusal is accepted
}
CLOSE_LABELS = {"LostToFollowUp": "Lost to follow-up", "Transferred": "Transferred to another hospital",
                "Deceased": "Deceased", "Declined": "Patient declined the biopsy / treatment"}
REOPENABLE = ("Closed-LostToFollowUp", "Closed-Declined", "Closed-Transferred")


class ContactIn(BaseModel):
    channel: Literal["SMS", "Phone", "Email", "InPerson", "Letter"]
    outcome: Literal["Reached", "NoAnswer", "WrongNumber", "Declined"]


class BiopsyIn(BaseModel):
    """Booking the biopsy appointment: only the date and time."""
    scheduled_for: datetime


class PathologyIn(BaseModel):
    diagnosis: Literal["Benign", "HighRiskLesion", "Malignant", "NonDiagnostic"]
    histology: Optional[str] = Field(None, max_length=100)


REFERRAL_SPECIALTIES = {"SurgicalOncology": "Surgical oncology", "MedicalOncology": "Medical oncology",
                        "RadiationOncology": "Radiation oncology"}


class AssignIn(BaseModel):
    assignee_staff_id: int
    specialty: Literal["SurgicalOncology", "MedicalOncology", "RadiationOncology"] = "SurgicalOncology"
    note: Optional[str] = Field(None, max_length=400)


class TreatmentIn(BaseModel):
    treatment_type: Literal["Surgery", "NeoadjuvantChemo", "Chemotherapy", "Radiation", "Endocrine", "Other"]


class ResultsAppointmentIn(BaseModel):
    clinician_staff_id: int
    scheduled_for: datetime


class DiscloseIn(BaseModel):
    channel: Literal["InPerson", "Phone"] = "InPerson"


class CloseLoopIn(BaseModel):
    reason: Literal["LostToFollowUp", "Transferred", "Deceased", "Declined"]
    note: str = Field(min_length=10, max_length=400)


class ReopenLoopIn(BaseModel):
    note: str = Field(min_length=10, max_length=400)


# ---------- helpers ---------------------------------------------------------------

def _log(conn, pid, event, actor=None, episode_id=None, **details):
    conn.execute(text("""
        INSERT INTO event_log (patient_id, episode_id, event_type, actor_id, details)
        VALUES (:p, :e, :t, :a, CAST(:d AS JSONB))
    """), {"p": pid, "e": episode_id, "t": event, "a": actor, "d": json.dumps(details, default=str)})


def _open_episode_id(conn, pid) -> int:
    disposition = conn.execute(text("""
        SELECT disposition FROM encounter WHERE patient_id = :p
        ORDER BY encounter_date DESC, encounter_id DESC LIMIT 1
    """), {"p": pid}).scalar()
    if disposition != "UrgentBiopsyReferral":
        raise HTTPException(status_code=409,
                            detail="The clinician must select urgent biopsy referral before using the care loop")
    eid = conn.execute(text(
        "SELECT episode_id FROM care_episode WHERE patient_id = :p AND status IN ('Open','Paused')"),
        {"p": pid}).scalar()
    if eid is None:
        raise HTTPException(status_code=409, detail="This patient has no open care loop")
    return eid


def _start_task(conn, episode_id, section, started_at=None):
    """Start an SLA clock. started_at=None means now."""
    conn.execute(text("""
        INSERT INTO sla_task (episode_id, section, started_at, due_at)
        SELECT :e, d.section, COALESCE(CAST(:t AS TIMESTAMPTZ), now()),
               COALESCE(CAST(:t AS TIMESTAMPTZ), now()) + make_interval(hours => d.target_hours)
        FROM sla_definition d WHERE d.section = :s
        ON CONFLICT (episode_id, section) DO NOTHING
    """), {"e": episode_id, "s": section, "t": started_at})


def _complete_task(conn, episode_id, section) -> bool:
    """Stop an SLA clock now. A late completion keeps status Breached. Resolves its alerts."""
    task_id = conn.execute(text("""
        UPDATE sla_task SET completed_at = now(),
               status = CASE WHEN now() <= due_at THEN 'Met' ELSE 'Breached' END
        WHERE episode_id = :e AND section = :s AND completed_at IS NULL AND status <> 'Cancelled'
        RETURNING sla_task_id
    """), {"e": episode_id, "s": section}).scalar()
    if task_id is not None:
        conn.execute(text("UPDATE sla_alert SET resolved_at = now() WHERE sla_task_id = :t AND resolved_at IS NULL"),
                     {"t": task_id})
    return task_id is not None


def _task_open(conn, episode_id, section) -> bool:
    return conn.execute(text("""
        SELECT 1 FROM sla_task WHERE episode_id = :e AND section = :s
          AND completed_at IS NULL AND status <> 'Cancelled'
    """), {"e": episode_id, "s": section}).first() is not None


def _require_task_completed(conn, episode_id, section, message: str):
    """Require the preceding care-loop step to have been completed."""
    done = conn.execute(text("""
        SELECT 1 FROM sla_task
        WHERE episode_id = :e AND section = :s AND completed_at IS NOT NULL
    """), {"e": episode_id, "s": section}).first()
    if done is None:
        raise HTTPException(status_code=409, detail=message)


# ---------- loop steps ------------------------------------------------------------

def open_episode(conn, pid) -> Optional[int]:
    """Called by the rules engine for a BI-RADS 4/5 result: open the loop, start S1, send the SMS."""
    existing = conn.execute(text(
        "SELECT episode_id FROM care_episode WHERE patient_id = :p AND status IN ('Open','Paused')"),
        {"p": pid}).scalar()
    if existing is not None:
        return existing
    img = conn.execute(text("""
        SELECT imaging_id, result_released_at, birads_category, modality FROM imaging_result
        WHERE patient_id = :p AND birads_category IN (4,5)
        ORDER BY result_released_at DESC LIMIT 1
    """), {"p": pid}).mappings().first()
    if img is None:
        return None
    # A loop already ran for this result (closed with a reason or finished): do not reopen it
    # silently. Reopening is a deliberate step (reopen_loop).
    if conn.execute(text("SELECT 1 FROM care_episode WHERE trigger_imaging_id = :i"),
                    {"i": img["imaging_id"]}).first():
        return None
    eid = conn.execute(text("""
        INSERT INTO care_episode (patient_id, trigger_imaging_id, opened_at)
        VALUES (:p, :i, :t) RETURNING episode_id
    """), {"p": pid, "i": img["imaging_id"], "t": img["result_released_at"]}).scalar()
    _start_task(conn, eid, 1, img["result_released_at"])   # S1 clock starts at result release
    conn.execute(text("""
        INSERT INTO patient_contact (episode_id, channel, attempted_at) VALUES (:e, 'SMS', now())
    """), {"e": eid})
    _log(conn, pid, "EpisodeOpened", episode_id=eid, imaging_id=img["imaging_id"])
    _log(conn, pid, "ResultSMSSent", episode_id=eid)
    _notify_oncology_team(conn, pid, eid, img["birads_category"], img["modality"])
    return eid


def _notify_oncology_team(conn, pid, eid, birads, modality):
    """Heads-up to the surgical and oncology team the moment the loop opens, so they are
    ready before the biopsy result arrives."""
    conn.execute(text("""
        INSERT INTO team_notification (patient_id, episode_id, routed_to_role, message)
        VALUES (:p, :e, :r, :m) ON CONFLICT (episode_id, routed_to_role) DO NOTHING
    """), {"p": pid, "e": eid, "r": ONCOLOGY_TEAM_ROLE,
           "m": f"BI-RADS {birads} ({modality}): urgent workup opened. "
                "Biopsy pending; be ready for a possible oncology referral."})
    _log(conn, pid, "OncologyTeamNotified", episode_id=eid, routed_to=ONCOLOGY_TEAM_ROLE)


def _resolve_notifications(conn, eid):
    conn.execute(text("UPDATE team_notification SET resolved_at = now() WHERE episode_id = :e AND resolved_at IS NULL"),
                 {"e": eid})


def _acknowledge(conn, pid, eid, actor=None):
    """Patient acknowledged the result: S1 met, S2 (biopsy booking) clock starts."""
    if not _task_open(conn, eid, 1):
        return
    _complete_task(conn, eid, 1)
    _start_task(conn, eid, 2)
    _log(conn, pid, "PatientAcknowledged", actor, eid)


def patient_acknowledge(pid: str) -> dict:
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        conn.execute(text("""
            UPDATE patient_contact SET acknowledged_at = now(), outcome = 'Reached'
            WHERE episode_id = :e AND acknowledged_at IS NULL AND outcome IS NULL
        """), {"e": eid})
        _acknowledge(conn, pid, eid)
    return {"acknowledged": True}


def record_contact(pid: str, data: ContactIn, staff_id: int) -> dict:
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        reached = data.outcome == "Reached"
        conn.execute(text("""
            INSERT INTO patient_contact (episode_id, channel, attempted_at, acknowledged_at, outcome, performed_by)
            VALUES (:e, :c, now(), CASE WHEN :r THEN now() END, :o, :s)
        """), {"e": eid, "c": data.channel, "r": reached, "o": data.outcome, "s": staff_id})
        _log(conn, pid, "ContactAttempt", staff_id, eid, channel=data.channel, outcome=data.outcome)
        if reached:
            _acknowledge(conn, pid, eid, staff_id)
    return {"recorded": True, "acknowledged": reached}


def book_biopsy(pid: str, data: BiopsyIn, staff_id: int) -> dict:
    """The navigator or scheduling manager books the biopsy appointment (date and time)."""
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        if conn.execute(text("SELECT 1 FROM biopsy WHERE episode_id = :e AND status IN ('Ordered','Booked')"),
                        {"e": eid}).first():
            raise HTTPException(status_code=409, detail="A biopsy is already booked for this patient")
        _require_task_completed(conn, eid, 1,
                                "The patient must confirm the result message before a biopsy can be booked")
        bid = conn.execute(text("""
            INSERT INTO biopsy (episode_id, ordered_at, booked_at, booked_by, scheduled_for, status)
            VALUES (:e, now(), now(), :s, :when, 'Booked') RETURNING biopsy_id
        """), {"e": eid, "s": staff_id, "when": data.scheduled_for}).scalar()
        _complete_task(conn, eid, 2)
        _log(conn, pid, "BiopsyBooked", staff_id, eid, biopsy_id=bid, scheduled_for=data.scheduled_for)
    return {"biopsy_id": bid}


def biopsy_performed(pid: str, staff_id: int) -> dict:
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        _require_task_completed(conn, eid, 2,
                                "The biopsy appointment must be booked before it can be marked as performed")
        bid = conn.execute(text("""
            UPDATE biopsy SET status = 'Performed', performed_at = now()
            WHERE biopsy_id = (SELECT biopsy_id FROM biopsy WHERE episode_id = :e AND status = 'Booked'
                               ORDER BY booked_at DESC LIMIT 1)
            RETURNING biopsy_id
        """), {"e": eid}).scalar()
        if bid is None:
            raise HTTPException(status_code=409, detail="No booked biopsy to mark as performed")
        _start_task(conn, eid, 3)
        _log(conn, pid, "BiopsyPerformed", staff_id, eid, biopsy_id=bid)
    return {"biopsy_id": bid}


def record_pathology(pid: str, data: PathologyIn, staff_id: int) -> dict:
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        bid = conn.execute(text("""
            SELECT b.biopsy_id FROM biopsy b
            WHERE b.episode_id = :e AND b.status = 'Performed'
              AND NOT EXISTS (SELECT 1 FROM pathology_result r WHERE r.biopsy_id = b.biopsy_id)
            ORDER BY b.performed_at DESC LIMIT 1
        """), {"e": eid}).scalar()
        if bid is None:
            raise HTTPException(status_code=409, detail="No performed biopsy is waiting for a report")
        conn.execute(text("""
            INSERT INTO pathology_result (biopsy_id, reported_at, diagnosis, histology, pathologist_id)
            VALUES (:b, now(), :d, :h, :s)
        """), {"b": bid, "d": data.diagnosis, "h": data.histology, "s": staff_id})
        _complete_task(conn, eid, 3)
        _log(conn, pid, "PathologyReported", staff_id, eid, biopsy_id=bid, diagnosis=data.diagnosis)

        if data.diagnosis == "Malignant":
            conn.execute(text("""
                INSERT INTO referral (patient_id, episode_id, specialty, created_at, status)
                VALUES (:p, :e, 'SurgicalOncology', now(), 'Pending')
            """), {"p": pid, "e": eid})
            _start_task(conn, eid, 4)
            _log(conn, pid, "MalignantConfirmed", staff_id, eid)
        else:
            _resolve_notifications(conn, eid)   # not cancer: the oncology team can stand down
    return {"diagnosis": data.diagnosis}


def assign_referral(pid: str, data: AssignIn, staff_id: int) -> dict:
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        _require_task_completed(conn, eid, 3,
                                "The pathology report must be completed before an oncology referral can be sent")
        ok = conn.execute(text(
            "SELECT 1 FROM staff WHERE staff_id = :s AND is_active AND role = 'TumorBoard'"),
            {"s": data.assignee_staff_id}).first()
        if not ok:
            raise HTTPException(status_code=422, detail="Choose an oncologist from the oncology team")
        rid = conn.execute(text("""
            UPDATE referral SET assigned_to_id = :a, assigned_at = now(), status = 'Assigned',
                   specialty = :sp, referred_by = :by, referral_note = :n
            WHERE referral_id = (SELECT referral_id FROM referral WHERE episode_id = :e AND status = 'Pending'
                                 ORDER BY created_at LIMIT 1)
            RETURNING referral_id
        """), {"a": data.assignee_staff_id, "e": eid, "sp": data.specialty, "by": staff_id,
               "n": data.note}).scalar()
        if rid is None:
            raise HTTPException(status_code=409, detail="No pending referral to assign")
        _complete_task(conn, eid, 4)
        _start_task(conn, eid, 5)
        _log(conn, pid, "ReferralAssigned", staff_id, eid, referral_id=rid, assignee=data.assignee_staff_id)
    return {"referral_id": rid}


def start_treatment(pid: str, data: TreatmentIn, staff_id: int) -> dict:
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        _require_task_completed(conn, eid, 4,
                                "The oncology referral must be assigned before treatment can start")
        malignant = conn.execute(text("""
            SELECT 1 FROM pathology_result r JOIN biopsy b ON b.biopsy_id = r.biopsy_id
            WHERE b.episode_id = :e AND r.diagnosis = 'Malignant'
        """), {"e": eid}).first()
        if not malignant:
            raise HTTPException(status_code=409, detail="Treatment can only start after a malignant result")
        if not conn.execute(text("""
            SELECT 1 FROM pathology_result r JOIN biopsy b ON b.biopsy_id = r.biopsy_id
            WHERE b.episode_id = :e AND r.diagnosis = 'Malignant' AND r.disclosed_at IS NOT NULL
        """), {"e": eid}).first():
            raise HTTPException(status_code=409,
                                detail="Tell the patient their result first (Results for the patient) before recording treatment")
        conn.execute(text("""
            INSERT INTO treatment (episode_id, treatment_type, ordered_at, started_at) VALUES (:e, :t, now(), now())
        """), {"e": eid, "t": data.treatment_type})
        _complete_task(conn, eid, 5)
        # Loop closed: stop any clock still running and clear its alerts
        conn.execute(text("""
            UPDATE sla_alert SET resolved_at = now()
            WHERE resolved_at IS NULL AND sla_task_id IN
                  (SELECT sla_task_id FROM sla_task WHERE episode_id = :e AND completed_at IS NULL)
        """), {"e": eid})
        conn.execute(text("""
            UPDATE sla_task SET status = 'Cancelled' WHERE episode_id = :e AND completed_at IS NULL
        """), {"e": eid})
        _resolve_notifications(conn, eid)
        conn.execute(text("""
            UPDATE care_episode SET status = 'Closed-TreatmentStarted', closed_at = now(),
                   closure_note = :n WHERE episode_id = :e
        """), {"e": eid, "n": f"Treatment started: {data.treatment_type}"})
        _log(conn, pid, "TreatmentStarted", staff_id, eid, treatment_type=data.treatment_type)
    return {"closed": True}


# ---------- telling the patient their biopsy result ------------------------------

def _undisclosed_pathology(conn, pid):
    """The latest biopsy report for this patient that nobody has gone through with them yet."""
    row = conn.execute(text("""
        SELECT r.pathology_id, r.diagnosis, b.episode_id FROM pathology_result r
        JOIN biopsy b ON b.biopsy_id = r.biopsy_id
        JOIN care_episode e ON e.episode_id = b.episode_id
        WHERE e.patient_id = :p AND r.disclosed_at IS NULL
        ORDER BY r.reported_at DESC LIMIT 1
    """), {"p": pid}).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="No biopsy report is waiting to be discussed with the patient")
    return row


def book_results_appointment(pid: str, data: ResultsAppointmentIn, staff_id: int, role: str = "Clinician") -> dict:
    """Book (or move) the appointment where a doctor goes through the biopsy result.
    A benign (or other non-cancer) result is handled on the clinical side only."""
    with engine.begin() as conn:
        path = _undisclosed_pathology(conn, pid)
        if role != "Clinician" and path["diagnosis"] != "Malignant":
            raise HTTPException(status_code=403, detail="Non-cancer biopsy results are handled by the clinician")
        doctor = conn.execute(text(
            "SELECT full_name FROM staff WHERE staff_id = :s AND is_active AND role = 'Clinician'"),
            {"s": data.clinician_staff_id}).scalar()
        if doctor is None:
            raise HTTPException(status_code=422, detail="Choose an active clinician for the appointment")
        conn.execute(text("""
            UPDATE results_appointment SET status = 'Cancelled'
            WHERE pathology_id = :r AND status = 'Booked'
        """), {"r": path["pathology_id"]})
        aid = conn.execute(text("""
            INSERT INTO results_appointment (patient_id, episode_id, pathology_id, clinician_id, scheduled_for, booked_by)
            VALUES (:p, :e, :r, :c, :t, :b) RETURNING appointment_id
        """), {"p": pid, "e": path["episode_id"], "r": path["pathology_id"], "c": data.clinician_staff_id,
               "t": data.scheduled_for, "b": staff_id}).scalar()
        _log(conn, pid, "ResultsAppointmentBooked", staff_id, path["episode_id"],
             appointment_id=aid, clinician=doctor, scheduled_for=data.scheduled_for)
    return {"appointment_id": aid, "clinician": doctor}


def disclose_result(pid: str, data: DiscloseIn, staff_id: int) -> dict:
    """The doctor has told the patient the result. From now on it shows on the patient's page."""
    with engine.begin() as conn:
        path = _undisclosed_pathology(conn, pid)
        conn.execute(text("""
            UPDATE pathology_result SET disclosed_at = now(), disclosed_by = :s, disclosure_channel = :c
            WHERE pathology_id = :r
        """), {"r": path["pathology_id"], "s": staff_id, "c": data.channel})
        conn.execute(text("""
            UPDATE results_appointment SET status = 'Completed', completed_at = now()
            WHERE pathology_id = :r AND status = 'Booked'
        """), {"r": path["pathology_id"]})
        _log(conn, pid, "ResultDisclosedToPatient", staff_id, path["episode_id"],
             pathology_id=path["pathology_id"], channel=data.channel)
        benign = conn.execute(text("SELECT diagnosis FROM pathology_result WHERE pathology_id = :r"),
                              {"r": path["pathology_id"]}).scalar() == "Benign"
        if benign:
            _close_benign(conn, pid, path["episode_id"], staff_id)
    return {"disclosed": True, "loop_closed": benign}


def _close_benign(conn, pid, eid, staff_id):
    """Benign biopsy, result gone through with the patient: the care loop ends and the patient
    goes back to imaging follow-up (a check scan in 6 months)."""
    tasks = conn.execute(text("""
        UPDATE sla_task SET status = 'Cancelled' WHERE episode_id = :e AND completed_at IS NULL
          AND status <> 'Cancelled' RETURNING sla_task_id
    """), {"e": eid}).scalars().all()
    if tasks:
        conn.execute(text("UPDATE sla_alert SET resolved_at = now() WHERE sla_task_id = ANY(:t) AND resolved_at IS NULL"),
                     {"t": list(tasks)})
    _resolve_notifications(conn, eid)
    conn.execute(text("""
        UPDATE care_episode SET status = 'Closed-Benign', closed_at = now(), closed_by = :s,
               closure_note = 'Benign biopsy; result discussed with the patient. Follow-up imaging in 6 months.'
        WHERE episode_id = :e
    """), {"e": eid, "s": staff_id})
    _log(conn, pid, "EpisodeClosed", staff_id, eid, reason="Benign")
    from app import followup           # local import: followup imports this module
    followup.schedule_after_benign(conn, pid, eid)


def referrals_to_make(scope_sql: str, params: dict) -> list[dict]:
    """Malignant biopsy results whose oncology referral the navigator still has to make (S4)."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(f"""
            SELECT p.patient_id, p.full_name, r.created_at, pr.histology, pr.reported_at,
                   FLOOR(EXTRACT(EPOCH FROM (t.due_at - now())) / 3600)::INT AS hours_left
            FROM referral r
            JOIN care_episode e ON e.episode_id = r.episode_id AND e.status IN ('Open','Paused')
            JOIN patient p ON p.patient_id = r.patient_id
            LEFT JOIN sla_task t ON t.episode_id = e.episode_id AND t.section = 4
            LEFT JOIN LATERAL (SELECT x.histology, x.reported_at FROM pathology_result x
                               JOIN biopsy b ON b.biopsy_id = x.biopsy_id
                               WHERE b.episode_id = e.episode_id AND x.diagnosis = 'Malignant'
                               ORDER BY x.reported_at DESC LIMIT 1) pr ON TRUE
            WHERE r.status = 'Pending' AND {scope_sql}
            ORDER BY t.due_at
        """), params).mappings()]


def results_to_discuss(scope_sql: str, params: dict, role: str = "Clinician") -> list[dict]:
    """Biopsy reports not yet gone through with the patient, for the patients this user may see.
    The navigator only sees malignant ones; benign results stay on the clinical side."""
    only = "" if role == "Clinician" else "AND r.diagnosis = 'Malignant'"
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(f"""
            SELECT p.patient_id, p.full_name, r.reported_at, r.diagnosis, a.scheduled_for, s.full_name AS doctor
            FROM pathology_result r
            JOIN biopsy b ON b.biopsy_id = r.biopsy_id
            JOIN care_episode e ON e.episode_id = b.episode_id
            JOIN patient p ON p.patient_id = e.patient_id
            LEFT JOIN results_appointment a ON a.pathology_id = r.pathology_id AND a.status = 'Booked'
            LEFT JOIN staff s ON s.staff_id = a.clinician_id
            WHERE r.disclosed_at IS NULL AND e.status IN ('Open','Paused') {only} AND {scope_sql}
            ORDER BY a.scheduled_for IS NOT NULL, r.reported_at
        """), params).mappings()]


# ---------- closing without treatment, and reopening -----------------------------

def failed_contacts(conn, eid) -> int:
    """Staff-recorded attempts that did not reach the patient."""
    return conn.execute(text("""
        SELECT COUNT(*) FROM patient_contact
        WHERE episode_id = :e AND performed_by IS NOT NULL AND outcome IN ('NoAnswer', 'WrongNumber')
    """), {"e": eid}).scalar()


def close_loop(pid: str, data: CloseLoopIn, user: dict) -> dict:
    if user["role"] not in CLOSE_REASONS[data.reason]:
        raise HTTPException(status_code=403, detail=f"{CLOSE_LABELS[data.reason]} can only be recorded by: "
                                                    + ", ".join(CLOSE_REASONS[data.reason]))
    staff_id = user.get("staff_id")
    with engine.begin() as conn:
        eid = _open_episode_id(conn, pid)
        conn.execute(text("""
            UPDATE care_episode SET status = :st, closed_at = now(), closed_by = :s, closure_note = :n
            WHERE episode_id = :e
        """), {"st": f"Closed-{data.reason}", "s": staff_id, "n": data.note.strip(), "e": eid})
        tasks = conn.execute(text("""
            UPDATE sla_task SET status = 'Cancelled'
            WHERE episode_id = :e AND completed_at IS NULL AND status <> 'Cancelled' RETURNING sla_task_id
        """), {"e": eid}).scalars().all()
        if tasks:
            conn.execute(text("UPDATE sla_alert SET resolved_at = now() WHERE sla_task_id = ANY(:t) AND resolved_at IS NULL"),
                         {"t": list(tasks)})
        conn.execute(text("""
            UPDATE biopsy SET status = CASE WHEN :r = 'Declined' THEN 'Declined' ELSE 'Cancelled' END
            WHERE episode_id = :e AND status IN ('Ordered', 'Booked')
        """), {"e": eid, "r": data.reason})
        conn.execute(text("""
            UPDATE results_appointment SET status = 'Cancelled' WHERE status = 'Booked' AND pathology_id IN
              (SELECT r.pathology_id FROM pathology_result r JOIN biopsy b ON b.biopsy_id = r.biopsy_id
               WHERE b.episode_id = :e)
        """), {"e": eid})
        conn.execute(text("UPDATE referral SET status = 'Cancelled' WHERE episode_id = :e AND status IN ('Pending', 'Assigned')"),
                     {"e": eid})
        _resolve_notifications(conn, eid)
        _log(conn, pid, "EpisodeClosed", staff_id, eid, reason=data.reason, note=data.note.strip(),
             clocks_stopped=len(tasks))
    return {"closed": True, "status": f"Closed-{data.reason}", "after": f"/?closed={pid}&kind=care"}


def reopen_loop(pid: str, data: ReopenLoopIn, staff_id: int) -> dict:
    """The patient came back (or was found): start a new loop from the same result, S1 from now."""
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM care_episode WHERE patient_id = :p AND status IN ('Open','Paused')"),
                        {"p": pid}).first():
            raise HTTPException(status_code=409, detail="This patient already has an open care loop")
        last = conn.execute(text("""
            SELECT episode_id, trigger_imaging_id, status FROM care_episode WHERE patient_id = :p
            ORDER BY opened_at DESC, episode_id DESC LIMIT 1
        """), {"p": pid}).mappings().first()
        if last is None or last["status"] not in REOPENABLE:
            raise HTTPException(status_code=409, detail="Only a loop closed as lost to follow-up, declined "
                                                        "or transferred can be reopened")
        eid = conn.execute(text("""
            INSERT INTO care_episode (patient_id, trigger_imaging_id, opened_at, reopened_from)
            VALUES (:p, :i, now(), :f) RETURNING episode_id
        """), {"p": pid, "i": last["trigger_imaging_id"], "f": last["episode_id"]}).scalar()
        _start_task(conn, eid, 1)
        conn.execute(text("INSERT INTO patient_contact (episode_id, channel, attempted_at) VALUES (:e, 'SMS', now())"),
                     {"e": eid})
        img = conn.execute(text("SELECT birads_category, modality FROM imaging_result WHERE imaging_id = :i"),
                           {"i": last["trigger_imaging_id"]}).mappings().one()
        _log(conn, pid, "EpisodeReopened", staff_id, eid, previous_episode=last["episode_id"],
             previous_status=last["status"], note=data.note.strip())
        _notify_oncology_team(conn, pid, eid, img["birads_category"], img["modality"])
    return {"reopened": True, "episode_id": eid}


def closed_without_treatment(limit: int = 50) -> list[dict]:
    """For the CMO: every care loop and imaging follow-up closed with a reason, newest first.
    The patient is off the working lists; the record stays here so the loop can be restarted."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT * FROM (
                SELECT 'care' AS kind, e.patient_id, p.full_name, e.status, e.closed_at, e.closure_note,
                       s.full_name AS closed_by_name, s.role AS closed_by_role,
                       'BI-RADS ' || i.birads_category || ' care loop' AS what,
                       (SELECT COUNT(*) FROM patient_contact c WHERE c.episode_id = e.episode_id
                          AND c.performed_by IS NOT NULL AND c.outcome IN ('NoAnswer','WrongNumber')) AS failed_contacts,
                       EXISTS (SELECT 1 FROM care_episode n WHERE n.reopened_from = e.episode_id) AS reopened
                FROM care_episode e
                JOIN patient p ON p.patient_id = e.patient_id
                JOIN imaging_result i ON i.imaging_id = e.trigger_imaging_id
                LEFT JOIN staff s ON s.staff_id = e.closed_by
                WHERE e.status IN ('Closed-LostToFollowUp','Closed-Declined','Closed-Transferred','Closed-Deceased')
                UNION ALL
                SELECT 'followup', f.patient_id, p.full_name, f.status, f.closed_at, f.closure_note,
                       s.full_name, s.role, 'Imaging follow-up (' || f.lane || ')',
                       (SELECT COUNT(*) FROM followup_contact c WHERE c.loop_id = f.loop_id
                          AND c.performed_by IS NOT NULL AND c.outcome IN ('NoAnswer','WrongNumber')),
                       EXISTS (SELECT 1 FROM followup_loop n WHERE n.reopened_from = f.loop_id)
                FROM followup_loop f
                JOIN patient p ON p.patient_id = f.patient_id
                LEFT JOIN staff s ON s.staff_id = f.closed_by
                WHERE f.status IN ('Closed-LostToFollowUp','Closed-Declined','Closed-Transferred','Closed-Deceased')
            ) x ORDER BY closed_at DESC LIMIT :n
        """), {"n": limit}).mappings()]


def closure_notice(pid: str, kind: str) -> Optional[dict]:
    """Shown once after a loop is closed: who the patient is and that they left the loop."""
    table = "care_episode" if kind == "care" else "followup_loop"
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT p.patient_id, p.full_name, l.status, l.closed_at FROM {table} l
            JOIN patient p ON p.patient_id = l.patient_id
            WHERE l.patient_id = :p ORDER BY l.closed_at DESC NULLS LAST LIMIT 1
        """), {"p": pid}).mappings().first()
    if row is None or row["status"] not in ("Closed-LostToFollowUp", "Closed-Declined",
                                            "Closed-Transferred", "Closed-Deceased"):
        return None
    reason = row["status"].replace("Closed-", "")
    return {**row, "kind": kind, "reason": CLOSE_LABELS.get(reason, reason),
            "loop_name": "care loop" if kind == "care" else "imaging follow-up"}


# ---------- breach checker --------------------------------------------------------

def check_sla() -> int:
    """Mark overdue tasks as Breached and send one alert each to the escalation role."""
    with engine.begin() as conn:
        breached = conn.execute(text("""
            UPDATE sla_task t SET status = 'Breached', escalation_level = 1, last_escalated_at = now()
            FROM care_episode e, sla_definition d
            WHERE e.episode_id = t.episode_id AND d.section = t.section
              AND t.status = 'Running' AND t.completed_at IS NULL AND t.due_at < now()
              AND e.status IN ('Open','Paused')
            RETURNING t.sla_task_id, t.section, t.episode_id, e.patient_id, d.escalation1_role
        """)).mappings().all()
        for b in breached:
            conn.execute(text("""
                INSERT INTO sla_alert (sla_task_id, patient_id, section, level, routed_to_role, action_text)
                VALUES (:t, :p, :s, 1, :r, :a) ON CONFLICT DO NOTHING
            """), {"t": b["sla_task_id"], "p": b["patient_id"], "s": b["section"],
                   "r": b["escalation1_role"], "a": ALERT_ACTIONS[b["section"]]})
            _log(conn, b["patient_id"], "SLABreached", episode_id=b["episode_id"],
                 section=b["section"], routed_to=b["escalation1_role"])
            if b["section"] == 1:
                _log(conn, b["patient_id"], "BackupCallStarted", episode_id=b["episode_id"])
            if b["section"] == 4:
                _log(conn, b["patient_id"], "ReferralRoutedToTumorBoard", episode_id=b["episode_id"])
    from app.followup import check_followups      # the imaging follow-up loop has its own clocks
    return len(breached) + check_followups()


# ---------- read side -------------------------------------------------------------

def open_alerts(role: str) -> list[dict]:
    """Open alerts for a role. The CMO sees every open alert (quality dashboard)."""
    where = "TRUE" if role == "CMO" else "a.routed_to_role = :r"
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(f"""
            SELECT a.alert_id, a.patient_id, p.full_name, a.section, d.name AS section_name,
                   a.routed_to_role, a.action_text, a.created_at, a.seen_at, t.due_at,
                   FLOOR(EXTRACT(EPOCH FROM (now() - t.due_at)) / 3600)::INT AS hours_overdue
            FROM sla_alert a
            JOIN patient p ON p.patient_id = a.patient_id
            JOIN sla_task t ON t.sla_task_id = a.sla_task_id
            JOIN sla_definition d ON d.section = a.section
            WHERE a.resolved_at IS NULL AND {where}
            ORDER BY a.section DESC, t.due_at
        """), {"r": role}).mappings()]


def mark_alert_seen(alert_id: int, user: dict) -> dict:
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE sla_alert SET seen_at = now(), seen_by = :s
            WHERE alert_id = :a AND seen_at IS NULL AND (routed_to_role = :r OR :r = 'CMO')
            RETURNING alert_id
        """), {"a": alert_id, "s": user.get("staff_id"), "r": user["role"]}).scalar()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found or already seen")
    return {"seen": True}


def open_notifications(role: str) -> list[dict]:
    """Open team notifications for a role (today: BI-RADS 4/5 heads-up to the Tumor Board)."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT n.notification_id, n.patient_id, p.full_name, n.message, n.created_at, n.seen_at
            FROM team_notification n JOIN patient p ON p.patient_id = n.patient_id
            WHERE n.resolved_at IS NULL AND n.routed_to_role = :r
            ORDER BY n.seen_at IS NOT NULL, n.created_at DESC
        """), {"r": role}).mappings()]


def mark_notification_seen(notification_id: int, user: dict) -> dict:
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE team_notification SET seen_at = now(), seen_by = :s
            WHERE notification_id = :n AND seen_at IS NULL AND routed_to_role = :r
            RETURNING notification_id
        """), {"n": notification_id, "s": user.get("staff_id"), "r": user["role"]}).scalar()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found or already seen")
    return {"seen": True}


def live_status(task) -> str:
    if task is None:
        return "Not started"
    if task["status"] == "Cancelled":
        return "Cancelled"
    if task["completed_at"] is not None:
        return "Met" if task["completed_at"] <= task["due_at"] else "Met late"
    return "Breached" if task["hours_left"] < 0 else "Running"


def get_loop(pid: str) -> dict:
    with engine.connect() as conn:
        patient = conn.execute(text("SELECT patient_id, full_name FROM patient WHERE patient_id = :p"),
                               {"p": pid}).mappings().first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        episode = conn.execute(text("""
            SELECT e.*, i.birads_category, i.modality FROM care_episode e
            JOIN imaging_result i ON i.imaging_id = e.trigger_imaging_id
            WHERE e.patient_id = :p ORDER BY e.opened_at DESC, e.episode_id DESC LIMIT 1
        """), {"p": pid}).mappings().first()
        disposition = conn.execute(text("""
            SELECT disposition FROM encounter WHERE patient_id = :p
            ORDER BY encounter_date DESC, encounter_id DESC LIMIT 1
        """), {"p": pid}).scalar()
        if disposition != "UrgentBiopsyReferral":
            episode = None
        ctx = {"patient": patient, "episode": episode, "sections": [], "contacts": [], "biopsy": None,
               "pathology": None, "referral": None, "treatment": None, "assignees": [],
               "results_appt": None, "clinicians": [], "failed_contacts": 0, "closed_by_name": None,
               "close_labels": CLOSE_LABELS, "close_reasons": CLOSE_REASONS,
               "reopenable": REOPENABLE, "specialties": REFERRAL_SPECIALTIES}
        if episode is None:
            return ctx
        e = {"e": episode["episode_id"]}
        ctx["failed_contacts"] = failed_contacts(conn, episode["episode_id"])
        if episode["closed_by"]:
            ctx["closed_by_name"] = conn.execute(text("SELECT full_name FROM staff WHERE staff_id = :s"),
                                                 {"s": episode["closed_by"]}).scalar()
        tasks = {t["section"]: t for t in conn.execute(text("""
            SELECT t.*, EXTRACT(EPOCH FROM (t.due_at - now())) / 3600 AS hours_left
            FROM sla_task t WHERE t.episode_id = :e
        """), e).mappings()}
        for d in conn.execute(text("SELECT * FROM sla_definition ORDER BY section")).mappings():
            t = tasks.get(d["section"])
            ctx["sections"].append({"def": d, "task": t, "status": live_status(t),
                                    "hours_left": int(t["hours_left"]) if t and t["hours_left"] is not None else None})
        ctx["contacts"] = conn.execute(text("""
            SELECT c.*, s.full_name AS by_name FROM patient_contact c LEFT JOIN staff s ON s.staff_id = c.performed_by
            WHERE c.episode_id = :e ORDER BY c.attempted_at DESC
        """), e).mappings().all()
        ctx["biopsy"] = conn.execute(text("""
            SELECT b.*, k.full_name AS booked_by_name FROM biopsy b LEFT JOIN staff k ON k.staff_id = b.booked_by
            WHERE b.episode_id = :e ORDER BY b.ordered_at DESC, b.biopsy_id DESC LIMIT 1
        """), e).mappings().first()
        ctx["pathology"] = conn.execute(text("""
            SELECT r.*, s.full_name AS disclosed_by_name, ps.full_name AS pathologist_name FROM pathology_result r
            JOIN biopsy b ON b.biopsy_id = r.biopsy_id
            LEFT JOIN staff s ON s.staff_id = r.disclosed_by
            LEFT JOIN staff ps ON ps.staff_id = r.pathologist_id
            WHERE b.episode_id = :e ORDER BY r.reported_at DESC LIMIT 1
        """), e).mappings().first()
        if ctx["pathology"]:
            ctx["results_appt"] = conn.execute(text("""
                SELECT a.*, s.full_name AS doctor FROM results_appointment a
                JOIN staff s ON s.staff_id = a.clinician_id
                WHERE a.pathology_id = :r AND a.status <> 'Cancelled'
                ORDER BY a.booked_at DESC LIMIT 1
            """), {"r": ctx["pathology"]["pathology_id"]}).mappings().first()
        ctx["clinicians"] = conn.execute(text("""
            SELECT s.staff_id, s.full_name,
                   EXISTS (SELECT 1 FROM care_team_assignment c
                           WHERE c.staff_id = s.staff_id AND c.patient_id = :p) AS on_team
            FROM staff s WHERE s.is_active AND s.role = 'Clinician'
            ORDER BY on_team DESC, s.full_name
        """), {"p": pid}).mappings().all()
        ctx["referral"] = conn.execute(text("""
            SELECT r.*, s.full_name AS assignee, rb.full_name AS referred_by_name FROM referral r
            LEFT JOIN staff s ON s.staff_id = r.assigned_to_id LEFT JOIN staff rb ON rb.staff_id = r.referred_by
            WHERE r.episode_id = :e ORDER BY r.created_at DESC LIMIT 1
        """), e).mappings().first()
        ctx["treatment"] = conn.execute(text(
            "SELECT * FROM treatment WHERE episode_id = :e ORDER BY started_at DESC LIMIT 1"), e).mappings().first()
        ctx["assignees"] = conn.execute(text("""
            SELECT staff_id, full_name, role FROM staff
            WHERE is_active AND role = 'TumorBoard' ORDER BY full_name
        """)).mappings().all()
    return ctx


def s1_pending(pid: str) -> bool:
    """True when the patient still has to acknowledge their result (shown on the patient page)."""
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT 1 FROM care_episode e JOIN sla_task t ON t.episode_id = e.episode_id AND t.section = 1
            WHERE e.patient_id = :p AND e.status IN ('Open','Paused')
              AND t.completed_at IS NULL AND t.status <> 'Cancelled'
        """), {"p": pid}).first() is not None


if __name__ == "__main__":
    # Start the loop for seeded patients the engine has never evaluated, then check for breaches.
    from app.rules_runner import run_engine
    with engine.connect() as c:
        todo = list(c.execute(text("""
            SELECT p.patient_id FROM patient p
            WHERE NOT EXISTS (SELECT 1 FROM lane_assignment l WHERE l.patient_id = p.patient_id)
              AND EXISTS (SELECT 1 FROM patient_risk_profile r WHERE r.patient_id = p.patient_id)
            ORDER BY p.patient_id
        """)).scalars())
    for pid in todo:
        print(pid, run_engine(pid)["lane"])
    print("SLA breaches found:", check_sla())
