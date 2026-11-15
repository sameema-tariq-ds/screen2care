# Which patients each role may see. The dashboard, the patient-list API and every
# per-patient route use the same rules, so a patient missing from your list is also
# blocked when you open their record directly.
from fastapi import HTTPException
from sqlalchemy import text

from app.database import engine

SEE_ALL_ROLES = ("Admin", "CMO")


def _open_sla(section: int) -> str:
    return f"""p.patient_id IN (SELECT e.patient_id FROM care_episode e
                JOIN sla_task t ON t.episode_id = e.episode_id
                WHERE t.section = {section} AND t.completed_at IS NULL AND t.status <> 'Cancelled'
                  AND e.status IN ('Open','Paused'))"""


def _followup_step(*steps: int) -> str:
    """Patients whose imaging follow-up loop is waiting on one of these steps (R1-R4)."""
    return f"""(SELECT l.patient_id FROM followup_loop l JOIN followup_task t ON t.loop_id = l.loop_id
                WHERE l.status = 'Open' AND t.completed_at IS NULL AND t.status <> 'Cancelled'
                  AND t.step IN ({",".join(str(s) for s in steps)}))"""


# SQL filter on patient alias "p". :sid is the logged-in user's staff_id.
ROLE_SCOPE = {
    "Clinician": "p.patient_id IN (SELECT patient_id FROM care_team_assignment WHERE staff_id = :sid)",
    "Radiologist": """p.patient_id IN (SELECT patient_id FROM imaging_result WHERE radiologist_id = :sid)
        OR p.patient_id IN """ + _followup_step(3, 4),
    "Pathologist": """p.patient_id IN (SELECT e.patient_id FROM care_episode e
                                       JOIN biopsy b ON b.episode_id = e.episode_id)""",
    "Navigator": """p.patient_id IN (SELECT patient_id FROM care_episode WHERE status IN ('Open','Paused'))
        OR p.patient_id IN (SELECT patient_id FROM followup_loop WHERE status = 'Open')""",
    "SchedulingManager": _open_sla(2) + " OR p.patient_id IN " + _followup_step(2),
    "LabDirector": _open_sla(3),
    "TumorBoard": _open_sla(4) + """ OR p.patient_id IN
        (SELECT patient_id FROM referral WHERE assigned_to_id = :sid)
        OR p.patient_id IN (SELECT patient_id FROM team_notification
                            WHERE routed_to_role = 'TumorBoard' AND resolved_at IS NULL)""",
    "Patient": "p.patient_id = :own_pid",
}

LIST_TITLES = {
    "Admin": "All registered patients",
    "CMO": "All patients (oversight)",
    "Clinician": "Patients assigned to you",
    "Radiologist": "Patients with imaging you reported",
    "Pathologist": "Patients with a biopsy on record",
    "Navigator": "Patients with an open care loop or imaging follow-up",
    "SchedulingManager": "Patients waiting for a biopsy booking (S2)",
    "LabDirector": "Biopsies waiting for a pathology report (S3)",
    "TumorBoard": "Urgent BI-RADS 4/5 workups and oncology referrals (S4)",
}


def scope_filter(user: dict) -> tuple[str, dict]:
    """Return a SQL condition on alias p, plus its parameters, for this user."""
    role = user["role"]
    if role in SEE_ALL_ROLES:
        return "TRUE", {}
    if role in ROLE_SCOPE:
        return f"({ROLE_SCOPE[role]})", {"sid": user.get("staff_id"), "own_pid": user.get("patient_id")}
    return "FALSE", {}


def can_access_patient(user: dict, patient_id: str) -> bool:
    cond, params = scope_filter(user)
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT 1 FROM patient p WHERE p.patient_id = :pid AND {cond}"),
            {**params, "pid": patient_id},
        ).first() is not None


def ensure_patient_access(user: dict, patient_id: str) -> None:
    if user["role"] == "Patient" and user.get("patient_id") != patient_id:
        raise HTTPException(status_code=403, detail="Patients can only see their own record")
    if user["role"] in SEE_ALL_ROLES:
        return  # a missing patient then gives 404 further on
    if not can_access_patient(user, patient_id):
        raise HTTPException(status_code=403, detail="This patient is not on your list")


# ---------- The role-filtered patient list (dashboard, API, Care Assistant) ----------

CLINICAL_LIST_FIELDS = ("birads_category", "density", "result_released_at",
                        "current_lane", "episode_status", "sla_section", "sla_hours_left",
                        "fu_status", "fu_due_date", "fu_step", "fu_hours_left")

PATIENT_LIST_SQL = """
    SELECT p.patient_id,
           p.full_name,
           date_part('year', age(p.date_of_birth))::int AS age,
           img.birads_category,
           img.density,
           img.result_released_at,
           la.lane AS current_lane,
           ep.status AS episode_status,
           sla.section AS sla_section,
           sla.hours_left AS sla_hours_left,
           fu.status AS fu_status, fu.due_date AS fu_due_date, fu.step AS fu_step, fu.hours_left AS fu_hours_left,
           (SELECT COUNT(*) FROM vw_data_quality_flags f WHERE f.patient_id = p.patient_id) AS flag_count
    FROM patient p
    LEFT JOIN lane_assignment la ON la.patient_id = p.patient_id AND la.is_current
    LEFT JOIN care_episode ep ON ep.patient_id = p.patient_id AND ep.status IN ('Open','Paused')
    LEFT JOIN LATERAL (
        SELECT i.birads_category, i.density, i.result_released_at
        FROM imaging_result i
        WHERE i.patient_id = p.patient_id
        ORDER BY i.result_released_at DESC, i.birads_category DESC, (i.density IS NULL)
        LIMIT 1
    ) img ON TRUE
    LEFT JOIN LATERAL (                      -- the most urgent SLA clock still running
        SELECT t.section, FLOOR(EXTRACT(EPOCH FROM (t.due_at - now())) / 3600)::INT AS hours_left
        FROM sla_task t
        WHERE t.episode_id = ep.episode_id AND t.completed_at IS NULL AND t.status <> 'Cancelled'
        ORDER BY t.due_at LIMIT 1
    ) sla ON TRUE
    LEFT JOIN LATERAL (                      -- imaging follow-up loop, if one is scheduled or open
        SELECT l.status, l.due_date, t.step,
               FLOOR(EXTRACT(EPOCH FROM (t.due_at - now())) / 3600)::INT AS hours_left
        FROM followup_loop l
        LEFT JOIN LATERAL (SELECT * FROM followup_task t WHERE t.loop_id = l.loop_id AND t.completed_at IS NULL
                           AND t.status <> 'Cancelled' ORDER BY t.due_at LIMIT 1) t ON TRUE
        WHERE l.patient_id = p.patient_id AND l.status IN ('Scheduled','Open') LIMIT 1
    ) fu ON TRUE
    WHERE {scope}
    ORDER BY p.patient_id
"""


def fetch_patients(user: dict) -> list[dict]:
    """The patient list this user's role is allowed to see."""
    cond, params = scope_filter(user)
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(PATIENT_LIST_SQL.format(scope=cond)), params).mappings()]
    # Keep active care-loop patients together at the top of the clinical worklist.
    rows.sort(key=lambda r: (0 if r.get("episode_status") else 1, r["patient_id"]))
    if user["role"] == "Admin":  # front desk: no clinical results
        for r in rows:
            for k in CLINICAL_LIST_FIELDS:
                r.pop(k, None)
    return rows
