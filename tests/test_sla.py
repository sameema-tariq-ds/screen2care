# End-to-end SLA loop on a throwaway patient (created and deleted by the fixture).
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import create_user
from app.care_loop import check_sla
from app.database import engine
from app.main import app
from app.seed_users import DEV_PASSWORD

PID = "TEST-SLA-01"
PATIENT_LOGIN = "test_sla_patient"


def logged_in(username: str) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/login", json={"username": username, "password": DEV_PASSWORD}).status_code == 200
    return client


def acknowledge_patient():
    return logged_in(PATIENT_LOGIN).post("/api/me/acknowledge")


def sql(query: str, **params):
    with engine.begin() as conn:
        return conn.execute(text(query), params)


def task(section: int) -> dict | None:
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT t.* FROM sla_task t JOIN care_episode e ON e.episode_id = t.episode_id
            WHERE e.patient_id = :p AND t.section = :s
        """), {"p": PID, "s": section}).mappings().first()


def alert_roles() -> dict[int, str]:
    with engine.connect() as conn:
        return {r.section: r.routed_to_role for r in conn.execute(text(
            "SELECT section, routed_to_role FROM sla_alert WHERE patient_id = :p AND resolved_at IS NULL"),
            {"p": PID})}


def make_overdue(section: int):
    sql("""UPDATE sla_task t SET started_at = now() - interval '30 days', due_at = now() - interval '1 hour'
           FROM care_episode e WHERE e.episode_id = t.episode_id AND e.patient_id = :p AND t.section = :s""",
        p=PID, s=section)


def cleanup():
    episodes = "(SELECT episode_id FROM care_episode WHERE patient_id = :p)"
    for q in [
        "DELETE FROM sla_alert WHERE patient_id = :p",
        "DELETE FROM team_notification WHERE patient_id = :p",
        f"DELETE FROM sla_task WHERE episode_id IN {episodes}",
        f"DELETE FROM patient_contact WHERE episode_id IN {episodes}",
        "DELETE FROM results_appointment WHERE patient_id = :p",
        f"DELETE FROM pathology_result WHERE biopsy_id IN (SELECT biopsy_id FROM biopsy WHERE episode_id IN {episodes})",
        f"DELETE FROM biopsy WHERE episode_id IN {episodes}",
        f"DELETE FROM treatment WHERE episode_id IN {episodes}",
        "DELETE FROM referral WHERE patient_id = :p",
        "DELETE FROM event_log WHERE patient_id = :p",
        "DELETE FROM lane_assignment WHERE patient_id = :p",
        "DELETE FROM care_episode WHERE patient_id = :p",
        "DELETE FROM followup_alert WHERE patient_id = :p",
        "DELETE FROM followup_task WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
        "DELETE FROM followup_contact WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
        "DELETE FROM followup_appointment WHERE loop_id IN (SELECT loop_id FROM followup_loop WHERE patient_id = :p)",
        "DELETE FROM followup_loop WHERE patient_id = :p",
        "DELETE FROM imaging_result WHERE patient_id = :p",
        "DELETE FROM encounter WHERE patient_id = :p",
        "DELETE FROM care_team_assignment WHERE patient_id = :p",
        "DELETE FROM patient_risk_profile WHERE patient_id = :p",
        "DELETE FROM app_user WHERE patient_id = :p",
        "DELETE FROM patient WHERE patient_id = :p",
    ]:
        sql(q, p=PID)


@pytest.fixture
def birads5_patient():
    """A 50-year-old with a BI-RADS 5 result released 2 hours ago, assigned to clinician1."""
    cleanup()
    sql("INSERT INTO patient (patient_id, full_name, date_of_birth, created_by) VALUES (:p, 'Test SLA', '1976-01-01', 1)", p=PID)
    sql("INSERT INTO patient_risk_profile (patient_id) VALUES (:p)", p=PID)
    sql("INSERT INTO care_team_assignment (patient_id, staff_id) VALUES (:p, 3)", p=PID)
    eid = sql("""INSERT INTO encounter (patient_id, encounter_date, encounter_type, entered_by, disposition)
                 VALUES (:p, now() - interval '1 day', 'Screening', 1, 'UrgentBiopsyReferral')
                 RETURNING encounter_id""", p=PID).scalar()
    sql("""INSERT INTO imaging_result (encounter_id, patient_id, modality, laterality, birads_category, density,
                                       result_released_at, radiologist_id)
           VALUES (:e, :p, 'Mammogram', 'B', 5, 'B', now() - interval '2 hours', 2)""", e=eid, p=PID)
    create_user(PATIENT_LOGIN, DEV_PASSWORD, "Patient", None, PID)
    yield PID
    cleanup()


def test_full_loop_with_every_escalation(birads5_patient):
    pid = birads5_patient
    clinician = logged_in("clinician1")

    # Engine opens the loop: S1 running, result SMS recorded
    assert clinician.post(f"/api/patients/{pid}/run-engine").json()["lane"] == "UrgentWorkup"
    assert task(1)["status"] == "Running"

    # S1 breach -> Navigator urgent dashboard
    make_overdue(1)
    assert check_sla() >= 1
    assert alert_roles() == {1: "Navigator"}
    navigator = logged_in("navigator1")
    assert any(a["patient_id"] == pid for a in navigator.get("/api/alerts").json())
    assert pid in navigator.get("/").text

    # Backup phone call reaches the patient -> S1 done (late), S2 starts, alert cleared
    assert navigator.post(f"/api/patients/{pid}/contact", json={"channel": "Phone", "outcome": "Reached"}).status_code == 200
    assert task(1)["completed_at"] is not None and task(1)["status"] == "Breached"
    assert task(2)["status"] == "Running"
    assert alert_roles() == {}

    # S2 breach -> Scheduling Manager, who books the emergency slot
    make_overdue(2)
    check_sla()
    assert alert_roles() == {2: "SchedulingManager"}
    scheduling = logged_in("scheduling1")
    assert any(a["section"] == 2 for a in scheduling.get("/api/alerts").json())
    assert logged_in("radiology1").post(f"/api/patients/{pid}/biopsy",
                                        json={"scheduled_for": "2030-01-01T09:00"}).status_code == 403
    assert scheduling.post(f"/api/patients/{pid}/biopsy",
                           json={"scheduled_for": "2030-01-01T09:00"}).status_code == 200
    assert task(2)["completed_at"] is not None

    # Radiologist performs it -> S3 starts; S3 breach -> Lab Director
    assert logged_in("radiology1").post(f"/api/patients/{pid}/biopsy/performed").status_code == 200
    assert task(3)["status"] == "Running"
    make_overdue(3)
    check_sla()
    assert alert_roles() == {3: "LabDirector"}
    assert any(a["section"] == 3 for a in logged_in("labdirector1").get("/api/alerts").json())

    # Malignant report -> S3 done, referral created, only S4 starts
    assert logged_in("pathology1").post(f"/api/patients/{pid}/pathology",
                                        json={"diagnosis": "Malignant", "histology": "IDC"}).status_code == 200
    assert task(4)["status"] == "Running" and task(5) is None

    # S4 breach -> Tumor Board; S5 does not exist until referral is assigned
    make_overdue(4)
    check_sla()
    assert alert_roles() == {4: "TumorBoard"}
    tumorboard = logged_in("tumorboard1")
    assert pid in tumorboard.get("/").text
    cmo_alerts = logged_in("cmo1").get("/api/alerts").json()
    assert {a["section"] for a in cmo_alerts if a["patient_id"] == pid} == {4}

    # The navigator makes the referral; the oncology team receives it
    assert tumorboard.post(f"/api/patients/{pid}/referral/assign", json={"assignee_staff_id": 8}).status_code == 403
    assert logged_in("navigator1").post(f"/api/patients/{pid}/referral/assign",
                                        json={"assignee_staff_id": 8}).status_code == 200
    assert task(5)["status"] == "Running"
    make_overdue(5)
    check_sla()
    assert alert_roles() == {5: "CMO"}

    # Treatment cannot be recorded before the patient has been told the result
    assert clinician.post(f"/api/patients/{pid}/treatment", json={"treatment_type": "Surgery"}).status_code == 409
    assert clinician.post(f"/api/patients/{pid}/result-disclosed", json={"channel": "InPerson"}).status_code == 200

    # Treatment closes the loop and clears the red flag
    assert clinician.post(f"/api/patients/{pid}/treatment", json={"treatment_type": "Surgery"}).status_code == 200
    assert task(5)["completed_at"] is not None
    assert alert_roles() == {}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM care_episode WHERE patient_id = :p"),
                            {"p": pid}).scalar() == "Closed-TreatmentStarted"
    assert "Closed-TreatmentStarted" in clinician.get(f"/loop/{pid}").text


def test_patient_acknowledges_in_time(birads5_patient):
    pid = birads5_patient
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")

    patient = logged_in(PATIENT_LOGIN)
    assert "Please confirm you received our message" in patient.get("/").text
    assert patient.post("/api/me/acknowledge").status_code == 200

    assert task(1)["status"] == "Met"
    assert task(2)["status"] == "Running"
    assert "Please confirm you received our message" not in patient.get("/").text
    check_sla()
    assert alert_roles() == {}


def test_benign_result_starts_no_oncology_clocks(birads5_patient):
    pid = birads5_patient
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    acknowledge_patient()
    logged_in("navigator1").post(f"/api/patients/{pid}/biopsy",
                                 json={"scheduled_for": "2030-01-01T09:00"})
    logged_in("radiology1").post(f"/api/patients/{pid}/biopsy/performed")
    logged_in("pathology1").post(f"/api/patients/{pid}/pathology", json={"diagnosis": "Benign"})
    assert task(3)["status"] == "Met"
    assert task(4) is None and task(5) is None


def test_roles_cannot_do_other_roles_steps(birads5_patient):
    pid = birads5_patient
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    assert logged_in("admin1").get(f"/loop/{pid}").status_code == 403
    assert logged_in("labdirector1").post(f"/api/patients/{pid}/pathology",
                                          json={"diagnosis": "Malignant"}).status_code == 403
    assert logged_in(PATIENT_LOGIN).post(f"/api/patients/{pid}/contact",
                                         json={"channel": "Phone", "outcome": "Reached"}).status_code == 403
    # clinician2 is not assigned to this patient
    assert logged_in("clinician2").post(f"/api/patients/{pid}/contact",
                                        json={"channel": "Phone", "outcome": "Reached"}).status_code == 403


# ---------- BI-RADS 4/5 heads-up to the surgical and oncology team -----------------

def notification() -> dict | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM team_notification WHERE patient_id = :p"),
                            {"p": PID}).mappings().first()


def test_birads5_notifies_oncology_team_at_once(birads5_patient):
    pid = birads5_patient
    assert notification() is None
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")

    # Sent when the loop opens, long before any biopsy or pathology
    n = notification()
    assert n["routed_to_role"] == "TumorBoard" and n["resolved_at"] is None
    assert "BI-RADS 5" in n["message"]
    assert task(4) is None                       # no referral clock yet

    tumorboard = logged_in("tumorboard1")
    assert pid in tumorboard.get("/").text       # patient is now on their list
    assert tumorboard.get(f"/loop/{pid}").status_code == 200
    mine = [x for x in tumorboard.get("/api/notifications").json() if x["patient_id"] == pid]
    assert len(mine) == 1 and mine[0]["seen_at"] is None

    # Only the Tumor Board can mark it seen, and only once
    nid = mine[0]["notification_id"]
    assert logged_in("navigator1").post(f"/api/notifications/{nid}/seen").status_code == 404
    assert tumorboard.post(f"/api/notifications/{nid}/seen").status_code == 200
    assert notification()["seen_at"] is not None
    assert tumorboard.post(f"/api/notifications/{nid}/seen").status_code == 404

    # Running the engine again does not send a second notification
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM team_notification WHERE patient_id = :p"),
                            {"p": pid}).scalar() == 1


def test_benign_result_stands_the_oncology_team_down(birads5_patient):
    pid = birads5_patient
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    acknowledge_patient()
    logged_in("navigator1").post(f"/api/patients/{pid}/biopsy",
                                 json={"scheduled_for": "2030-01-01T09:00"})
    logged_in("radiology1").post(f"/api/patients/{pid}/biopsy/performed")
    logged_in("pathology1").post(f"/api/patients/{pid}/pathology", json={"diagnosis": "Benign"})

    assert notification()["resolved_at"] is not None
    assert all(x["patient_id"] != pid for x in logged_in("tumorboard1").get("/api/notifications").json())
    assert logged_in("tumorboard1").get(f"/loop/{pid}").status_code == 403


def test_malignant_keeps_the_notification_until_treatment(birads5_patient):
    pid = birads5_patient
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    acknowledge_patient()
    logged_in("navigator1").post(f"/api/patients/{pid}/biopsy",
                                 json={"scheduled_for": "2030-01-01T09:00"})
    logged_in("radiology1").post(f"/api/patients/{pid}/biopsy/performed")
    logged_in("pathology1").post(f"/api/patients/{pid}/pathology", json={"diagnosis": "Malignant"})
    assert notification()["resolved_at"] is None

    logged_in("clinician1").post(f"/api/patients/{pid}/result-disclosed", json={"channel": "Phone"})
    logged_in("navigator1").post(f"/api/patients/{pid}/referral/assign", json={"assignee_staff_id": 8})
    logged_in("clinician1").post(f"/api/patients/{pid}/treatment", json={"treatment_type": "Surgery"})
    assert notification()["resolved_at"] is not None
