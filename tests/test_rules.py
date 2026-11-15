# Screening rules (Steps 1-4). The first tests call the pure logic in app/rules.py;
# the last ones run the engine against the database to check what it reads.
from datetime import date

import pytest
from sqlalchemy import text

from app.database import engine
from app.rules import Inputs, evaluate
from app.rules_runner import run_engine

TODAY = date(2026, 11, 8)


def inputs(**kw) -> Inputs:
    base = dict(eval_date=TODAY, age=50, genetic_status="Negative", chest_radiation_age=None,
                lifetime_risk_pct=None, high_risk_lesion=None, birads=1, density="B",
                life_expectancy_over_10y=None, severe_comorbidity=False)
    return Inputs(**{**base, **kw})


# ---------- Step 1: chest radiation start age = 8 years after, never before 25 -----------

@pytest.mark.parametrize("rad_age, age, lane", [
    (12, 22, "HighRisk-Waiting"),     # 12 + 8 = 20, but never before 25
    (12, 25, "HighRisk-MRIOnly"),
    (20, 26, "HighRisk-Waiting"),     # 20 + 8 = 28: not yet at 26
    (20, 28, "HighRisk-MRIOnly"),
    (25, 32, "HighRisk-Waiting"),     # 25 + 8 = 33
    (25, 33, "HighRisk-DBT+MRI"),     # age 30+: DBT and MRI alternating
])
def test_radiation_start_age(rad_age, age, lane):
    d = evaluate(inputs(chest_radiation_age=rad_age, age=age))
    assert d.lane == lane


def test_radiation_waiting_reason_names_the_start_age():
    d = evaluate(inputs(chest_radiation_age=20, age=26))
    assert "starts at age 28" in d.reason


def test_radiation_outside_10_to_30_is_not_high_risk():
    assert evaluate(inputs(chest_radiation_age=35, age=50)).lane == "RoutineScreening"


def test_gene_positive_starts_at_25():
    assert evaluate(inputs(genetic_status="Positive", age=24)).lane == "HighRisk-Waiting"
    assert evaluate(inputs(genetic_status="Positive", age=27)).lane == "HighRisk-MRIOnly"
    assert evaluate(inputs(genetic_status="Positive", age=31)).lane == "HighRisk-DBT+MRI"


def test_lifetime_risk_or_lesion_starts_at_30():
    assert evaluate(inputs(lifetime_risk_pct=22, age=29)).lane == "HighRisk-Waiting"
    assert evaluate(inputs(lifetime_risk_pct=22, age=35)).lane == "HighRisk-DBT+ConsiderMRI"
    assert evaluate(inputs(high_risk_lesion="LCIS", age=45)).lane == "HighRisk-DBT+ConsiderMRI"


# ---------- Steps 2 and 3 --------------------------------------------------------------

def test_average_risk_age_groups_and_birads_matrix():
    assert evaluate(inputs(age=35)).lane == "WellnessHold"
    assert evaluate(inputs(birads=2, density="A")).lane == "RoutineScreening"
    assert evaluate(inputs(birads=1, density="D")).lane == "DenseSupplemental"
    assert evaluate(inputs(birads=3)).lane == "ShortInterval6M"
    assert evaluate(inputs(birads=4)).lane == "UrgentWorkup"
    assert evaluate(inputs(birads=5, genetic_status="Positive", age=40)).lane == "UrgentWorkup"


# ---------- Step 4: age 75+ ------------------------------------------------------------

def test_over_75_rules():
    assert evaluate(inputs(age=80, life_expectancy_over_10y=True)).lane == "RoutineScreening"
    assert evaluate(inputs(age=80, life_expectancy_over_10y=False)).lane == "SymptomaticCareOnly"
    assert evaluate(inputs(age=80, life_expectancy_over_10y=None)).lane == "DataPending"
    # A serious condition ends screening even when life expectancy is long or not yet known
    assert evaluate(inputs(age=80, life_expectancy_over_10y=True, severe_comorbidity=True)).lane == "SymptomaticCareOnly"
    assert evaluate(inputs(age=80, severe_comorbidity=True)).lane == "SymptomaticCareOnly"
    # A suspicious result still wins at any age
    assert evaluate(inputs(age=80, birads=5, life_expectancy_over_10y=False)).lane == "UrgentWorkup"


# ---------- Engine reads life expectancy from the geriatric assessment ----------------

PID = "TEST-RULES-75"


def sql(q, **p):
    with engine.begin() as conn:
        return conn.execute(text(q), p)


def cleanup():
    for q in [
        "DELETE FROM event_log WHERE patient_id = :p",
        "DELETE FROM lane_assignment WHERE patient_id = :p",
        "DELETE FROM geriatric_assessment WHERE encounter_id IN (SELECT encounter_id FROM encounter WHERE patient_id = :p)",
        "DELETE FROM followup_alert WHERE patient_id = :p",
        "DELETE FROM followup_task WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
        "DELETE FROM followup_contact WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
        "DELETE FROM followup_appointment WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
        "DELETE FROM followup_loop WHERE patient_id = :p",
        "DELETE FROM imaging_result WHERE patient_id = :p",
        "DELETE FROM encounter WHERE patient_id = :p",
        "DELETE FROM patient_risk_profile WHERE patient_id = :p",
        "DELETE FROM patient WHERE patient_id = :p",
    ]:
        sql(q, p=PID)


@pytest.fixture
def patient_80():
    """An 80-year-old with a normal mammogram. Returns a function that records the geriatric answers."""
    cleanup()
    sql("INSERT INTO patient (patient_id, full_name, date_of_birth, created_by) VALUES (:p, 'Test Rules', '1946-01-01', 1)", p=PID)
    sql("INSERT INTO patient_risk_profile (patient_id) VALUES (:p)", p=PID)
    eid = sql("""INSERT INTO encounter (patient_id, encounter_date, encounter_type, entered_by)
                 VALUES (:p, now(), 'Screening', 1) RETURNING encounter_id""", p=PID).scalar()
    sql("""INSERT INTO imaging_result (encounter_id, patient_id, modality, laterality, birads_category, density,
                                       result_released_at) VALUES (:e, :p, 'Mammogram', 'B', 1, 'B', now())""",
        e=eid, p=PID)

    def geriatric(end_stage: bool, life_exp):
        sql("DELETE FROM geriatric_assessment WHERE encounter_id = :e", e=eid)
        sql("""INSERT INTO geriatric_assessment (encounter_id, end_stage_organ_failure_or_dementia,
                                                 independent_in_adl, life_expectancy_over_10y)
               VALUES (:e, :es, TRUE, :le)""", e=eid, es=end_stage, le=life_exp)
    yield geriatric
    cleanup()


def test_engine_uses_recorded_life_expectancy(patient_80):
    patient_80(end_stage=False, life_exp=True)
    assert run_engine(PID)["lane"] == "RoutineScreening"
    patient_80(end_stage=False, life_exp=False)
    assert run_engine(PID)["lane"] == "SymptomaticCareOnly"
    patient_80(end_stage=False, life_exp=None)
    assert run_engine(PID)["lane"] == "DataPending"


def test_engine_treats_end_stage_illness_as_serious(patient_80):
    patient_80(end_stage=True, life_exp=None)
    assert run_engine(PID)["lane"] == "SymptomaticCareOnly"


# ---------- Intake form -> geriatric_assessment -> engine ------------------------------

INTAKE_NID = "35202-7654321-5"


def remove_intake_patient():
    pid = sql("SELECT patient_id FROM patient WHERE national_id = :n", n=INTAKE_NID).scalar()
    if pid is None:
        return
    enc = "(SELECT encounter_id FROM encounter WHERE patient_id = :p)"
    for q in ["DELETE FROM lane_assignment WHERE patient_id = :p",
              "DELETE FROM event_log WHERE patient_id = :p",
              "DELETE FROM care_team_assignment WHERE patient_id = :p",
              "DELETE FROM risk_assessment WHERE patient_id = :p",
              "DELETE FROM encounter_snapshot WHERE patient_id = :p",
              "DELETE FROM plan_items WHERE patient_id = :p",
              f"DELETE FROM geriatric_assessment WHERE encounter_id IN {enc}",
              f"DELETE FROM clinical_breast_exam WHERE encounter_id IN {enc}",
              f"DELETE FROM clinical_note WHERE encounter_id IN {enc}",
              "DELETE FROM followup_alert WHERE patient_id = :p",
              "DELETE FROM followup_task WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
              "DELETE FROM followup_contact WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
              "DELETE FROM followup_appointment WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
              "DELETE FROM followup_loop WHERE patient_id = :p",
              "DELETE FROM imaging_result WHERE patient_id = :p",
              "DELETE FROM encounter WHERE patient_id = :p",
              "DELETE FROM family_history WHERE patient_id = :p",
              "DELETE FROM prior_breast_procedure WHERE patient_id = :p",
              "DELETE FROM comorbidity WHERE patient_id = :p",
              "DELETE FROM patient_risk_profile WHERE patient_id = :p",
              "DELETE FROM patient WHERE patient_id = :p"]:
        sql(q, p=pid)


def test_intake_form_life_expectancy_reaches_the_engine():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.seed_users import DEV_PASSWORD

    cbe = {"inspection": "Normal", "mass": "Normal", "axillary_nodes": "Normal"}
    form = {"evaluation_date": TODAY.isoformat(), "presentation": False,
            "marital_status": "Married", "height_cm": 160, "weight_kg": 60,
            "chest_radiation": "No", "genetic_status": "Never tested",
            "geriatric_end_stage_failure": "No", "geriatric_adl_independent": "Yes",
            "geriatric_life_expectancy_over_10y": True, "family_history_none": True,
            "cbe_right": cbe, "cbe_left": cbe,
            "imaging": [{"date": TODAY.isoformat(), "modality": "Mammogram", "density": "B", "birads": 1}],
            "plan": ["Routine Rescreening (Mammogram/DBT in 12–24 Months)"],
            "signed_date": TODAY.isoformat()}
    remove_intake_patient()
    try:
        admin, doctor = TestClient(app), TestClient(app)
        assert admin.post("/api/login", json={"username": "admin1", "password": DEV_PASSWORD}).status_code == 200
        reg = admin.post("/api/registration", json={
            "full_name": "Test Rules Intake", "date_of_birth": "1946-03-01", "national_id": INTAKE_NID,
            "phone": "03001234567", "clinician_staff_id": 3})
        assert reg.status_code == 201, reg.text
        assert doctor.post("/api/login", json={"username": "clinician1", "password": DEV_PASSWORD}).status_code == 200
        res = doctor.post("/api/intake", json={**form, "patient_id": reg.json()["patient_id"]})
        assert res.status_code == 201, res.text
        assert res.json()["lane"] == "RoutineScreening"          # was DataPending before the fix
        saved = sql("""SELECT g.life_expectancy_over_10y FROM geriatric_assessment g
                       JOIN encounter e ON e.encounter_id = g.encounter_id
                       WHERE e.patient_id = :p""", p=res.json()["patient_id"]).scalar()
        assert saved is True
    finally:
        remove_intake_patient()
