# Imaging follow-up loop: a separate loop for patients whose next step is more imaging
# (BI-RADS 0 recall, BI-RADS 3 six-month scan, annual / dense / high-risk screening).
# BI-RADS 4/5 patients stay in the care loop (app/care_loop.py, S1-S5).
#
#   R1  reminder sent        -> patient confirms     14 days (never past the due date) -> Navigator
#   R2  patient confirmed    -> imaging booked       by the due date                   -> Scheduling Manager
#   R3  imaging booked       -> scan done            due date + grace period           -> Navigator
#   R4  scan done            -> result reported      3 days                            -> Clinician
#
# The loop starts as "Scheduled" and opens (reminder SMS, R1 clock) a set number of days
# before the due date. When a new result is saved, the rules engine closes the loop:
# BI-RADS 4/5 hands the patient to the care loop, anything else schedules the next loop.
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from app.care_loop import CLOSE_LABELS, CLOSE_REASONS
from app.database import engine

# lane -> what imaging is due, how many days before the due date the reminder goes out,
# and how many days after the due date the scan may still happen before it is overdue
LANES = {
    "RecallBirads0": {"imaging": "Recall imaging after BI-RADS 0 (diagnostic mammogram / ultrasound)",
                      "lead": 30, "grace": 7},
    "ShortInterval6M": {"imaging": "6-month follow-up scan after BI-RADS 3", "lead": 30, "grace": 14},
    "RoutineScreening": {"imaging": "Annual screening mammogram / DBT", "lead": 30, "grace": 30},
    "DenseSupplemental": {"imaging": "Annual mammogram with supplemental ultrasound / MRI", "lead": 30, "grace": 30},
    "HighRisk-MRIOnly": {"imaging": "Annual breast MRI (high risk)", "lead": 30, "grace": 30},
    "HighRisk-DBT+MRI": {"imaging": "High-risk DBT / MRI (alternating every 6 months)", "lead": 30, "grace": 30},
    "HighRisk-DBT+ConsiderMRI": {"imaging": "Annual DBT, consider MRI (high risk)", "lead": 30, "grace": 30},
    "PostBenignBiopsy": {"imaging": "Check scan 6 months after a benign biopsy", "lead": 30, "grace": 14},
}

STEPS = {
    1: {"name": "Reminder confirmed", "role": "Navigator",
        "action": "The patient has not confirmed the screening reminder. Call the patient."},
    2: {"name": "Imaging booked", "role": "SchedulingManager",
        "action": "Follow-up imaging is due and not booked. Book a slot now."},
    3: {"name": "Scan done", "role": "Navigator",
        "action": "The follow-up scan has not been done. Contact the patient and rebook."},
    4: {"name": "Result reported", "role": "Clinician",
        "action": "The follow-up scan was done 3 days ago and the result is not recorded. Record the BI-RADS result."},
}
REPORT_HOURS = 72
CONFIRM_DAYS = 14

STEP_ROLES = {
    "contact": ("Navigator", "Clinician"),
    "book": ("Navigator", "SchedulingManager"),
    "performed": ("Radiologist", "Navigator"),
    "report": ("Clinician", "Radiologist"),
    "close": ("CMO", "Navigator", "Clinician"),
    "reopen": ("CMO", "Clinician"),
}
ACTIVE = ("Scheduled", "Open")
CLOSED_WITH_REASON = ("Closed-LostToFollowUp", "Closed-Declined", "Closed-Transferred", "Closed-Deceased")
REOPENABLE = ("Closed-LostToFollowUp", "Closed-Declined", "Closed-Transferred")


class FollowupContactIn(BaseModel):
    channel: Literal["SMS", "Phone", "Email", "InPerson", "Letter"]
    outcome: Literal["Reached", "NoAnswer", "WrongNumber", "Declined"]


class FollowupBookIn(BaseModel):
    modality: Literal["Mammogram", "DBT", "Ultrasound", "MRI"]
    scheduled_for: datetime

    @field_validator("scheduled_for")
    @classmethod
    def as_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class FollowupReportIn(BaseModel):
    birads: int = Field(ge=0, le=6)
    density: Optional[Literal["A", "B", "C", "D"]] = None
    report_text: Optional[str] = Field(None, max_length=2000)


class FollowupCloseIn(BaseModel):
    reason: Literal["LostToFollowUp", "Transferred", "Deceased", "Declined"]
    note: str = Field(min_length=10, max_length=400)


class FollowupReopenIn(BaseModel):
    note: str = Field(min_length=10, max_length=400)


# ---------- helpers ---------------------------------------------------------------

def _log(conn, pid, event, actor=None, **details):
    conn.execute(text("""
        INSERT INTO event_log (patient_id, event_type, actor_id, details) VALUES (:p, :t, :a, CAST(:d AS JSONB))
    """), {"p": pid, "t": event, "a": actor, "d": json.dumps(details, default=str)})


def _end_of(d: date) -> datetime:
    return datetime.combine(d, time(23, 59), tzinfo=timezone.utc)


def _start(conn, loop_id, step, due_at):
    conn.execute(text("""
        INSERT INTO followup_task (loop_id, step, started_at, due_at) VALUES (:l, :s, now(), :d)
        ON CONFLICT (loop_id, step) DO NOTHING
    """), {"l": loop_id, "s": step, "d": due_at})


def _complete(conn, loop_id, step) -> bool:
    task = conn.execute(text("""
        UPDATE followup_task SET completed_at = now(),
               status = CASE WHEN now() <= due_at THEN 'Met' ELSE 'Breached' END
        WHERE loop_id = :l AND step = :s AND completed_at IS NULL AND status <> 'Cancelled'
        RETURNING task_id
    """), {"l": loop_id, "s": step}).scalar()
    if task is not None:
        conn.execute(text("UPDATE followup_alert SET resolved_at = now() WHERE task_id = :t AND resolved_at IS NULL"),
                     {"t": task})
    return task is not None


def _running(conn, loop_id, step) -> bool:
    return conn.execute(text("""
        SELECT 1 FROM followup_task WHERE loop_id = :l AND step = :s AND completed_at IS NULL AND status <> 'Cancelled'
    """), {"l": loop_id, "s": step}).first() is not None


def _stop_all(conn, loop_id, how: str):
    """Finish every clock still running: 'complete' (the result is in) or 'cancel' (closed with a reason)."""
    if how == "complete":
        for step in range(1, 5):
            _complete(conn, loop_id, step)
        return
    tasks = conn.execute(text("""
        UPDATE followup_task SET status = 'Cancelled' WHERE loop_id = :l AND completed_at IS NULL
          AND status <> 'Cancelled' RETURNING task_id
    """), {"l": loop_id}).scalars().all()
    if tasks:
        conn.execute(text("UPDATE followup_alert SET resolved_at = now() WHERE task_id = ANY(:t) AND resolved_at IS NULL"),
                     {"t": list(tasks)})


def _open_loop(conn, pid) -> dict:
    loop = conn.execute(text("SELECT * FROM followup_loop WHERE patient_id = :p AND status = 'Open'"),
                        {"p": pid}).mappings().first()
    if loop is None:
        raise HTTPException(status_code=409, detail="This patient has no open imaging follow-up loop")
    return loop


def _recommendation_satisfied(conn, pid: str, lane: str, due_date: date | None) -> bool:
    """Do not open an overdue loop when the recommended scan was completed on time."""
    if due_date is None:
        return False
    if lane == "HighRisk-MRIOnly":
        modalities = ("MRI",)
    elif lane in ("RoutineScreening", "HighRisk-DBT+MRI"):
        modalities = ("Mammogram", "DBT", "MRI")
    else:
        modalities = ("Mammogram", "DBT", "Ultrasound", "MRI")
    return conn.execute(text("""
        SELECT 1 FROM imaging_result
        WHERE patient_id = :p AND performed_date >= :due
          AND modality = ANY(:modalities)
        LIMIT 1
    """), {"p": pid, "due": due_date, "modalities": list(modalities)}).first() is not None


# ---------- called by the rules engine ------------------------------------------

def sync(conn, pid: str, lane: str, next_due: Optional[date], latest_imaging_id: Optional[int]) -> None:
    """Keep the follow-up loop in step with the latest lane.

    A newer result than the one that started the loop closes it (the scan was done);
    BI-RADS 4/5 closes it as escalated (the care loop takes over). A follow-up lane with
    a due date then gets a new scheduled loop, once per result."""
    active = conn.execute(text("SELECT * FROM followup_loop WHERE patient_id = :p AND status IN ('Scheduled','Open')"),
                          {"p": pid}).mappings().first()
    if active and (lane == "UrgentWorkup" or
                   (latest_imaging_id and active["source_imaging_id"] != latest_imaging_id)):
        status = "Closed-Escalated" if lane == "UrgentWorkup" else "Closed-Completed"
        _stop_all(conn, active["loop_id"], "complete")
        conn.execute(text("""
            UPDATE followup_appointment SET status = CASE WHEN status = 'Booked' THEN 'Performed' ELSE status END,
                   performed_at = COALESCE(performed_at, now())
            WHERE loop_id = :l AND status = 'Booked'
        """), {"l": active["loop_id"]})
        conn.execute(text("""
            UPDATE followup_loop SET status = :s, closed_at = now(), result_imaging_id = :i WHERE loop_id = :l
        """), {"s": status, "i": latest_imaging_id, "l": active["loop_id"]})
        _log(conn, pid, "FollowupClosed", status=status, loop_id=active["loop_id"], result_imaging_id=latest_imaging_id)
        active = None

    if active or lane not in LANES or next_due is None:
        return
    if conn.execute(text("SELECT 1 FROM care_episode WHERE patient_id = :p AND status IN ('Open','Paused')"),
                    {"p": pid}).first():
        return                     # the care loop is running: it decides the next step
    if latest_imaging_id and conn.execute(text("SELECT 1 FROM followup_loop WHERE source_imaging_id = :i"),
                                          {"i": latest_imaging_id}).first():
        return                     # this result already had its loop (closed with a reason or done)
    if _recommendation_satisfied(conn, pid, lane, next_due):
        return                     # the recommended imaging was recorded on or after its due date
    loop_id = conn.execute(text("""
        INSERT INTO followup_loop (patient_id, lane, source_imaging_id, due_date) VALUES (:p, :l, :i, :d)
        RETURNING loop_id
    """), {"p": pid, "l": lane, "i": latest_imaging_id, "d": next_due}).scalar()
    _log(conn, pid, "FollowupScheduled", loop_id=loop_id, lane=lane, due_date=next_due)
    _activate(conn, only_loop=loop_id)


def schedule_after_benign(conn, pid: str, episode_id: int) -> None:
    """Called when a benign biopsy result has been discussed: check scan in 6 months."""
    if conn.execute(text("SELECT 1 FROM followup_loop WHERE patient_id = :p AND status IN ('Scheduled','Open')"),
                    {"p": pid}).first():
        return
    src = conn.execute(text("SELECT trigger_imaging_id FROM care_episode WHERE episode_id = :e"),
                       {"e": episode_id}).scalar()
    loop_id = conn.execute(text("""
        INSERT INTO followup_loop (patient_id, lane, source_imaging_id, due_date)
        VALUES (:p, 'PostBenignBiopsy', :i, current_date + 182) RETURNING loop_id
    """), {"p": pid, "i": src}).scalar()
    _log(conn, pid, "FollowupScheduled", loop_id=loop_id, lane="PostBenignBiopsy")


# ---------- clock checker (runs with the care-loop SLA check) ----------------------

def _activate(conn, only_loop: Optional[int] = None) -> int:
    """Open scheduled loops whose reminder date has come: send the reminder, start R1."""
    rows = conn.execute(text("""
        SELECT loop_id, patient_id, lane, due_date FROM followup_loop
        WHERE status = 'Scheduled' AND (CAST(:only AS INT) IS NULL OR loop_id = :only)
    """), {"only": only_loop}).mappings().all()
    today, opened = date.today(), 0
    for r in rows:
        lead = LANES.get(r["lane"], {"lead": 30})["lead"]
        if r["due_date"] - timedelta(days=lead) > today:
            continue
        now = datetime.now(timezone.utc)
        due = max(min(now + timedelta(days=CONFIRM_DAYS), _end_of(r["due_date"])), now + timedelta(days=2))
        conn.execute(text("UPDATE followup_loop SET status = 'Open', opened_at = now() WHERE loop_id = :l"),
                     {"l": r["loop_id"]})
        _start(conn, r["loop_id"], 1, due)
        conn.execute(text("INSERT INTO followup_contact (loop_id, channel) VALUES (:l, 'SMS')"), {"l": r["loop_id"]})
        _log(conn, r["patient_id"], "FollowupReminderSent", loop_id=r["loop_id"], due_date=r["due_date"])
        opened += 1
    return opened


def check_followups() -> int:
    """Open loops that are due and send an alert for each follow-up clock that has run out."""
    with engine.begin() as conn:
        _activate(conn)
        breached = conn.execute(text("""
            UPDATE followup_task t SET status = 'Breached'
            FROM followup_loop l
            WHERE l.loop_id = t.loop_id AND l.status = 'Open'
              AND t.status = 'Running' AND t.completed_at IS NULL AND t.due_at < now()
            RETURNING t.task_id, t.step, l.patient_id, l.loop_id
        """)).mappings().all()
        for b in breached:
            step = STEPS[b["step"]]
            conn.execute(text("""
                INSERT INTO followup_alert (task_id, patient_id, step, routed_to_role, action_text)
                VALUES (:t, :p, :s, :r, :a) ON CONFLICT DO NOTHING
            """), {"t": b["task_id"], "p": b["patient_id"], "s": b["step"], "r": step["role"], "a": step["action"]})
            _log(conn, b["patient_id"], "FollowupOverdue", loop_id=b["loop_id"], step=f"R{b['step']}",
                 routed_to=step["role"])
    return len(breached)


# ---------- loop steps ------------------------------------------------------------

def _confirm(conn, loop):
    if _complete(conn, loop["loop_id"], 1):
        now = datetime.now(timezone.utc)
        _start(conn, loop["loop_id"], 2, max(_end_of(loop["due_date"]), now + timedelta(days=3)))


def patient_confirm(pid: str) -> dict:
    with engine.begin() as conn:
        loop = _open_loop(conn, pid)
        if not _running(conn, loop["loop_id"], 1):
            raise HTTPException(status_code=409, detail="Nothing to confirm")
        conn.execute(text("INSERT INTO followup_contact (loop_id, channel, outcome) VALUES (:l, 'Portal', 'Reached')"),
                     {"l": loop["loop_id"]})
        _confirm(conn, loop)
        _log(conn, pid, "FollowupConfirmedByPatient", loop_id=loop["loop_id"])
    return {"confirmed": True}


def record_contact(pid: str, data: FollowupContactIn, staff_id) -> dict:
    with engine.begin() as conn:
        loop = _open_loop(conn, pid)
        conn.execute(text("""
            INSERT INTO followup_contact (loop_id, channel, outcome, performed_by) VALUES (:l, :c, :o, :s)
        """), {"l": loop["loop_id"], "c": data.channel, "o": data.outcome, "s": staff_id})
        if data.outcome == "Reached":
            _confirm(conn, loop)
        _log(conn, pid, "FollowupContact", staff_id, loop_id=loop["loop_id"], channel=data.channel, outcome=data.outcome)
    return {"recorded": True}


def book(pid: str, data: FollowupBookIn, staff_id) -> dict:
    with engine.begin() as conn:
        loop = _open_loop(conn, pid)
        _confirm(conn, loop)                 # booking with the patient also counts as their confirmation
        conn.execute(text("UPDATE followup_appointment SET status = 'Cancelled' WHERE loop_id = :l AND status = 'Booked'"),
                     {"l": loop["loop_id"]})
        conn.execute(text("""
            INSERT INTO followup_appointment (loop_id, modality, scheduled_for, booked_by) VALUES (:l, :m, :t, :s)
        """), {"l": loop["loop_id"], "m": data.modality, "t": data.scheduled_for, "s": staff_id})
        _complete(conn, loop["loop_id"], 2)
        grace = LANES.get(loop["lane"], {"grace": 30})["grace"]
        due = max(_end_of(loop["due_date"]), data.scheduled_for) + timedelta(days=grace)
        conn.execute(text("UPDATE followup_task SET due_at = :d WHERE loop_id = :l AND step = 3 AND completed_at IS NULL"),
                     {"d": due, "l": loop["loop_id"]})       # rebooking moves the scan deadline
        _start(conn, loop["loop_id"], 3, due)
        _log(conn, pid, "FollowupBooked", staff_id, loop_id=loop["loop_id"], modality=data.modality,
             scheduled_for=data.scheduled_for)
    return {"booked": True}


def performed(pid: str, staff_id) -> dict:
    with engine.begin() as conn:
        loop = _open_loop(conn, pid)
        appt = conn.execute(text("""
            UPDATE followup_appointment SET status = 'Performed', performed_at = now()
            WHERE loop_id = :l AND status = 'Booked' RETURNING appointment_id
        """), {"l": loop["loop_id"]}).scalar()
        if appt is None:
            raise HTTPException(status_code=409, detail="No booked scan to mark as done")
        _complete(conn, loop["loop_id"], 3)
        _start(conn, loop["loop_id"], 4, datetime.now(timezone.utc) + timedelta(hours=REPORT_HOURS))
        _log(conn, pid, "FollowupScanDone", staff_id, loop_id=loop["loop_id"])
    return {"performed": True}


def report(pid: str, data: FollowupReportIn, staff_id) -> dict:
    """Record the follow-up result, then let the rules engine decide: BI-RADS 4/5 opens
    the care loop, anything else closes this loop and schedules the next one."""
    with engine.begin() as conn:
        loop = _open_loop(conn, pid)
        appt = conn.execute(text("""
            SELECT modality FROM followup_appointment WHERE loop_id = :l AND status = 'Performed'
            ORDER BY performed_at DESC LIMIT 1
        """), {"l": loop["loop_id"]}).mappings().first()
        if appt is None:
            raise HTTPException(status_code=409, detail="Mark the scan as done before recording its result")
        enc = conn.execute(text("""
            INSERT INTO encounter (patient_id, encounter_date, encounter_type, entered_by, chief_complaint)
            VALUES (:p, now(), :t, :s, :c) RETURNING encounter_id
        """), {"p": pid, "t": "Recall" if loop["lane"] == "RecallBirads0" else "FollowUp", "s": staff_id,
               "c": f"Imaging follow-up: {LANES.get(loop['lane'], {}).get('imaging', loop['lane'])}"[:200]}).scalar()
        density = data.density if appt["modality"] in ("Mammogram", "DBT") else None
        conn.execute(text("""
            INSERT INTO imaging_result (encounter_id, patient_id, modality, laterality, birads_category, density,
                                        result_released_at, radiologist_id, report_text)
            VALUES (:e, :p, :m, 'B', :b, :d, now(), :s, :r)
        """), {"e": enc, "p": pid, "m": appt["modality"], "b": data.birads, "d": density, "s": staff_id,
               "r": data.report_text})
        _log(conn, pid, "FollowupResultRecorded", staff_id, loop_id=loop["loop_id"], birads=data.birads)
    from app.rules_runner import run_engine          # local import: rules_runner imports this module
    result = run_engine(pid)
    return {"recorded": True, "lane": result["lane"], "care_loop_opened": result["lane"] == "UrgentWorkup"}


def close(pid: str, data: FollowupCloseIn, user: dict) -> dict:
    if user["role"] not in CLOSE_REASONS[data.reason]:
        raise HTTPException(status_code=403, detail=f"{CLOSE_LABELS[data.reason]} can only be recorded by: "
                                                    + ", ".join(CLOSE_REASONS[data.reason]))
    with engine.begin() as conn:
        loop = _open_loop(conn, pid)
        _stop_all(conn, loop["loop_id"], "cancel")
        conn.execute(text("UPDATE followup_appointment SET status = 'Cancelled' WHERE loop_id = :l AND status = 'Booked'"),
                     {"l": loop["loop_id"]})
        conn.execute(text("""
            UPDATE followup_loop SET status = :s, closed_at = now(), closed_by = :b, closure_note = :n WHERE loop_id = :l
        """), {"s": f"Closed-{data.reason}", "b": user.get("staff_id"), "n": data.note.strip(), "l": loop["loop_id"]})
        _log(conn, pid, "FollowupClosed", user.get("staff_id"), loop_id=loop["loop_id"], status=f"Closed-{data.reason}",
             note=data.note.strip())
    return {"closed": True, "after": f"/?closed={pid}&kind=followup"}


def reopen(pid: str, data: FollowupReopenIn, staff_id) -> dict:
    """The patient came back: a new follow-up starts with the scan due now (reminder sent at once)."""
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM followup_loop WHERE patient_id = :p AND status IN ('Scheduled','Open')"),
                        {"p": pid}).first():
            raise HTTPException(status_code=409, detail="This patient already has an active imaging follow-up")
        last = conn.execute(text("""
            SELECT * FROM followup_loop WHERE patient_id = :p ORDER BY created_at DESC, loop_id DESC LIMIT 1
        """), {"p": pid}).mappings().first()
        if last is None or last["status"] not in REOPENABLE:
            raise HTTPException(status_code=409, detail="Only a follow-up closed as lost to follow-up, declined "
                                                        "or transferred can be restarted")
        loop_id = conn.execute(text("""
            INSERT INTO followup_loop (patient_id, lane, source_imaging_id, due_date, reopened_from)
            VALUES (:p, :l, :i, current_date, :f) RETURNING loop_id
        """), {"p": pid, "l": last["lane"], "i": last["source_imaging_id"], "f": last["loop_id"]}).scalar()
        _log(conn, pid, "FollowupReopened", staff_id, loop_id=loop_id, previous_loop=last["loop_id"],
             note=data.note.strip())
        _activate(conn, only_loop=loop_id)
    return {"reopened": True}


def failed_contacts(conn, loop_id) -> int:
    return conn.execute(text("""
        SELECT COUNT(*) FROM followup_contact
        WHERE loop_id = :l AND performed_by IS NOT NULL AND outcome IN ('NoAnswer', 'WrongNumber')
    """), {"l": loop_id}).scalar()


# ---------- read side -------------------------------------------------------------

def _status(task) -> str:
    if task is None:
        return "Not started"
    if task["status"] == "Cancelled":
        return "Cancelled"
    if task["completed_at"] is not None:
        return "Met" if task["completed_at"] <= task["due_at"] else "Met late"
    return "Breached" if task["due_at"] < datetime.now(timezone.utc) else "Running"


def get_followup(pid: str) -> dict:
    with engine.connect() as conn:
        patient = conn.execute(text("SELECT patient_id, full_name FROM patient WHERE patient_id = :p"),
                               {"p": pid}).mappings().first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        loop = conn.execute(text("""
            SELECT f.*, s.full_name AS closed_by_name FROM followup_loop f LEFT JOIN staff s ON s.staff_id = f.closed_by
            WHERE f.patient_id = :p ORDER BY f.created_at DESC, f.loop_id DESC LIMIT 1
        """), {"p": pid}).mappings().first()
        ctx = {"patient": patient, "loop": loop, "steps": [], "contacts": [], "appointment": None,
               "history": [], "failed_contacts": 0, "lane_info": None, "result": None,
               "close_labels": CLOSE_LABELS, "reopenable": REOPENABLE}
        if loop is None:
            return ctx
        lid = {"l": loop["loop_id"]}
        ctx["lane_info"] = LANES.get(loop["lane"])
        tasks = {t["step"]: t for t in conn.execute(text("SELECT * FROM followup_task WHERE loop_id = :l"), lid).mappings()}
        now = datetime.now(timezone.utc)
        for n, d in STEPS.items():
            t = tasks.get(n)
            ctx["steps"].append({"n": n, **d, "task": t, "status": _status(t),
                                 "hours_left": int((t["due_at"] - now).total_seconds() // 3600) if t else None})
        ctx["contacts"] = conn.execute(text("""
            SELECT c.*, s.full_name AS by_name FROM followup_contact c LEFT JOIN staff s ON s.staff_id = c.performed_by
            WHERE c.loop_id = :l ORDER BY c.attempted_at DESC
        """), lid).mappings().all()
        ctx["appointment"] = conn.execute(text("""
            SELECT * FROM followup_appointment WHERE loop_id = :l AND status <> 'Cancelled'
            ORDER BY booked_at DESC LIMIT 1
        """), lid).mappings().first()
        ctx["failed_contacts"] = failed_contacts(conn, loop["loop_id"])
        if loop["result_imaging_id"]:
            ctx["result"] = conn.execute(text("SELECT * FROM imaging_result WHERE imaging_id = :i"),
                                         {"i": loop["result_imaging_id"]}).mappings().first()
        ctx["history"] = conn.execute(text("""
            SELECT loop_id, lane, due_date, status, closed_at FROM followup_loop
            WHERE patient_id = :p AND loop_id <> :l ORDER BY created_at DESC
        """), {"p": pid, "l": loop["loop_id"]}).mappings().all()
    return ctx


WORK_FOR_ROLE = {          # which open steps each role works on (dashboard list)
    "Navigator": (1, 2, 3), "SchedulingManager": (2,), "Radiologist": (3, 4), "Clinician": (4,),
}


def worklist(user: dict, scope_sql: str, params: dict) -> list[dict]:
    """Open follow-up loops this role should act on, most overdue first. The CMO sees overdue ones."""
    role = user["role"]
    if role == "CMO":
        step_filter = "t.due_at < now()"
    elif role in WORK_FOR_ROLE:
        step_filter = "t.step IN (" + ",".join(str(s) for s in WORK_FOR_ROLE[role]) + ")"
    else:
        return []
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT l.patient_id, p.full_name, l.lane, l.due_date, t.step, t.due_at,
                   FLOOR(EXTRACT(EPOCH FROM (t.due_at - now())) / 3600)::INT AS hours_left
            FROM followup_loop l
            JOIN patient p ON p.patient_id = l.patient_id
            JOIN followup_task t ON t.loop_id = l.loop_id AND t.completed_at IS NULL AND t.status <> 'Cancelled'
            WHERE l.status = 'Open' AND {step_filter} AND {scope_sql}
            ORDER BY t.due_at
        """), params).mappings().all()
    return [{**r, "step_name": STEPS[r["step"]]["name"], "imaging": LANES.get(r["lane"], {}).get("imaging", r["lane"])}
            for r in rows]


def upcoming_count() -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM followup_loop WHERE status = 'Scheduled'")).scalar()


def patient_view(pid: str) -> Optional[dict]:
    """What the patient sees about their next scan."""
    with engine.connect() as conn:
        loop = conn.execute(text("""
            SELECT * FROM followup_loop WHERE patient_id = :p AND status IN ('Scheduled','Open')
        """), {"p": pid}).mappings().first()
        if loop is None:
            return None
        appt = conn.execute(text("""
            SELECT modality, scheduled_for, status FROM followup_appointment
            WHERE loop_id = :l AND status IN ('Booked','Performed') ORDER BY booked_at DESC LIMIT 1
        """), {"l": loop["loop_id"]}).mappings().first()
        confirm = loop["status"] == "Open" and _running(conn, loop["loop_id"], 1)
    return {"due_date": loop["due_date"], "imaging": LANES.get(loop["lane"], {}).get("imaging", "Follow-up imaging"),
            "confirm_needed": confirm, "appointment": dict(appt) if appt else None}
