from datetime import datetime

from sqlalchemy import text

from app import followup
from app.care_loop import open_episode
from app.database import engine
from app.rules import Inputs, evaluate
from app.schemas import PlanOption


PLAN_LANES = {
    PlanOption.ROUTINE_RESCREEN.value: "RoutineScreening",
    PlanOption.SHORT_TERM_FOLLOW_UP.value: "ShortInterval6M",
    PlanOption.ANNUAL_MRI.value: "HighRisk-MRIOnly",
    PlanOption.ANNUAL_DBT_MRI_6M.value: "HighRisk-DBT+MRI",
}


def _doctor_plan(conn, patient_id: str):
    """Return the latest explicit clinician disposition and planned due date."""
    rows = conn.execute(text("""
        WITH latest AS (
            SELECT encounter_id, disposition, plan_options
            FROM encounter
            WHERE patient_id = :p
            ORDER BY encounter_date DESC, encounter_id DESC
            LIMIT 1
        )
        SELECT latest.disposition, latest.plan_options, pi.plan_option, pi.due_date
        FROM latest
        LEFT JOIN plan_items pi ON pi.encounter_id = latest.encounter_id AND pi.status = 'Planned'
        ORDER BY pi.due_date NULLS LAST
    """), {"p": patient_id}).mappings().all()
    if not rows:
        return None
    if rows[0]["disposition"] == "UrgentBiopsyReferral":
        return "UrgentWorkup", None
    if any(any(str(option).startswith("Stop Routine Screening") for option in (row["plan_options"] or []))
           for row in rows):
        return "SymptomaticCareOnly", None
    for row in rows:
        lane = PLAN_LANES.get(row["plan_option"])
        if lane:
            return lane, row["due_date"]
    return None

def load_inputs(conn, patient_id: str) -> Inputs:
    p = conn.execute(text("""
        SELECT p.date_of_birth, r.genetic_status, r.chest_radiation_age, r.lifetime_risk_pct,
               r.high_risk_lesion AS lesion,
               (SELECT COUNT(*) > 0 FROM comorbidity c
                 WHERE c.patient_id = p.patient_id AND c.is_severe_active) AS severe,
               g.end_stage_organ_failure_or_dementia AS end_stage,
               g.life_expectancy_over_10y AS life_exp
        FROM patient p JOIN patient_risk_profile r USING (patient_id)
        LEFT JOIN LATERAL (                 -- latest geriatric assessment, if any
            SELECT ga.* FROM geriatric_assessment ga
            JOIN encounter en ON en.encounter_id = ga.encounter_id
            WHERE en.patient_id = p.patient_id
            ORDER BY en.encounter_date DESC LIMIT 1
        ) g ON TRUE
        WHERE p.patient_id = :pid
    """), {"pid": patient_id}).mappings().one()

    latest = conn.execute(text("""
        SELECT birads_category, density, result_released_at FROM imaging_result
        WHERE patient_id = :pid ORDER BY result_released_at DESC, birads_category DESC LIMIT 1
    """), {"pid": patient_id}).mappings().first()

    today = datetime.now().date()
    dob = p["date_of_birth"]
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    return Inputs(
        eval_date=today,
        age=age,
        genetic_status=p["genetic_status"],
        chest_radiation_age=p["chest_radiation_age"],
        lifetime_risk_pct=float(p["lifetime_risk_pct"]) if p["lifetime_risk_pct"] is not None else None,
        high_risk_lesion=p["lesion"],
        birads=latest["birads_category"] if latest else None,
        density=latest["density"] if latest else None,
        life_expectancy_over_10y=p["life_exp"],
        # end-stage organ failure or advanced dementia counts as a serious condition
        severe_comorbidity=bool(p["severe"] or p["end_stage"]),
    )


def run_engine(patient_id: str) -> dict:
    with engine.begin() as conn:
        inputs = load_inputs(conn, patient_id)
        d = evaluate(inputs)
        planned = _doctor_plan(conn, patient_id)
        # Risk-derived findings do not open the five-step SLA by themselves.
        # The clinician's explicit plan controls whether this is urgent workup
        # or a planned imaging notification/follow-up.
        lane, next_due = planned if planned else ("DataPending", None)

        conn.execute(text("UPDATE lane_assignment SET is_current = FALSE WHERE patient_id = :pid AND is_current"),
                     {"pid": patient_id})
        conn.execute(text("""
            INSERT INTO lane_assignment (patient_id, lane, next_due_date, reason, assigned_by)
            VALUES (:pid, :lane, :due, :reason, 'Engine')
        """), {"pid": patient_id, "lane": lane, "due": next_due,
                "reason": d.reason if not planned else f"Clinician disposition: {lane}"})

        latest_imaging = conn.execute(text("""
            SELECT imaging_id FROM imaging_result WHERE patient_id = :pid
            ORDER BY result_released_at DESC, birads_category DESC LIMIT 1
        """), {"pid": patient_id}).scalar()
        # Imaging follow-up loop (BI-RADS 0/3, annual, dense, high risk). Runs first so a
        # BI-RADS 4/5 result closes it before the care loop opens.
        followup.sync(conn, patient_id, lane, next_due, latest_imaging)
        if lane == "UrgentWorkup":
            open_episode(conn, patient_id)   # starts S1 and sends the result SMS

    return {"patient_id": patient_id, "lane": lane, "reason": d.reason,
            "next_due": str(next_due) if next_due else None, "flags": d.flags}
