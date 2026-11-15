# The patient follows their own care loop, and hears the biopsy result from a doctor first:
# report ready -> results appointment -> doctor discusses it -> result on the patient's page.
from sqlalchemy import text

from app.database import engine
from tests.test_sla import PATIENT_LOGIN, birads5_patient, logged_in  # noqa: F401  (fixture)


def patient_page() -> str:
    return logged_in(PATIENT_LOGIN).get("/").text


def staff_name(staff_id: int) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT full_name FROM staff WHERE staff_id = :s"), {"s": staff_id}).scalar()


def to_report(pid: str, diagnosis: str = "Malignant"):
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    logged_in(PATIENT_LOGIN).post("/api/me/acknowledge")
    logged_in("navigator1").post(f"/api/patients/{pid}/biopsy",
                                 json={"scheduled_for": "2030-01-01T09:00"})
    logged_in("radiology1").post(f"/api/patients/{pid}/biopsy/performed")
    assert logged_in("pathology1").post(f"/api/patients/{pid}/pathology",
                                        json={"diagnosis": diagnosis, "histology": "IDC"}).status_code == 200


def test_patient_page_follows_every_stage(birads5_patient):
    pid = birads5_patient
    logged_in("clinician1").post(f"/api/patients/{pid}/run-engine")
    assert "Your progress" not in patient_page()            # nothing booked yet: status as before
    logged_in(PATIENT_LOGIN).post("/api/me/acknowledge")
    logged_in("navigator1").post(f"/api/patients/{pid}/biopsy",
                                 json={"scheduled_for": "2030-01-01T09:00"})
    page = patient_page()
    assert "Your progress" in page and "Biopsy booked" in page and "Tue 01 Jan at 09:00" in page

    logged_in("radiology1").post(f"/api/patients/{pid}/biopsy/performed")
    page = patient_page()
    assert "Biopsy done" in page and "being examined in the laboratory" in page
    assert "Biopsy" in page                                  # listed under past visits


def test_report_ready_but_result_hidden_until_the_doctor_tells_the_patient(birads5_patient):
    pid = birads5_patient
    to_report(pid, "Malignant")

    page = patient_page()
    assert "Your report is ready" in page and "We will book an appointment with your doctor" in page
    for secret in ("Malignant", "breast cancer", "IDC", "Specialist team assigned"):
        assert secret not in page

    # The doctor's dashboard lists it as waiting for an appointment
    dash = logged_in("clinician1").get("/").text
    assert "Biopsy results to go through with the patient" in dash and "No appointment booked yet" in dash

    # Who may book: Navigator and Clinician only, and only with a clinician
    body = {"clinician_staff_id": 3, "scheduled_for": "2030-01-05T10:30"}
    assert logged_in("radiology1").post(f"/api/patients/{pid}/results-appointment", json=body).status_code == 403
    assert logged_in("navigator1").post(f"/api/patients/{pid}/results-appointment",
                                        json={**body, "clinician_staff_id": 8}).status_code == 422
    assert logged_in("navigator1").post(f"/api/patients/{pid}/results-appointment", json=body).status_code == 200

    doctor = staff_name(3)
    page = patient_page()
    assert f"Results appointment with {doctor}" in page
    assert f"{doctor} will go through your biopsy result with you on Sat 05 Jan at 10:30" in page
    assert "Malignant" not in page and "breast cancer" not in page

    # Moving it keeps one live appointment
    assert logged_in("clinician1").post(f"/api/patients/{pid}/results-appointment",
                                        json={**body, "scheduled_for": "2030-01-06T11:00"}).status_code == 200
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM results_appointment WHERE patient_id = :p AND status = 'Booked'"),
                            {"p": pid}).scalar() == 1

    # Only a clinician can record that the result was discussed
    assert logged_in("navigator1").post(f"/api/patients/{pid}/result-disclosed", json={}).status_code == 403
    clinician = logged_in("clinician1")
    assert clinician.post(f"/api/patients/{pid}/result-disclosed", json={"channel": "InPerson"}).status_code == 200
    assert clinician.post(f"/api/patients/{pid}/result-disclosed", json={}).status_code == 409   # only once

    page = patient_page()
    assert "Specialist care" in page and "Your biopsy found breast cancer" in page
    assert f"Results discussed with {doctor}" in page
    assert "Specialist team assigned" in page and "Treatment started" in page   # next steps now visible
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM results_appointment WHERE patient_id = :p AND status <> 'Cancelled'"),
                            {"p": pid}).scalar() == "Completed"
    assert pid not in logged_in("clinician1").get("/").text.split("Biopsy results to go through")[-1].split("Patients")[0]

    # Another patient never sees any of this
    assert "Your biopsy found breast cancer" not in logged_in("patient1").get("/").text


def test_benign_result_after_phone_call(birads5_patient):
    pid = birads5_patient
    to_report(pid, "Benign")
    assert "No cancer found" not in patient_page()
    assert logged_in("clinician1").post(f"/api/patients/{pid}/result-disclosed",
                                        json={"channel": "Phone"}).status_code == 200
    page = patient_page()
    assert "No cancer found" in page and "Your biopsy showed no cancer" in page
    assert "Specialist team assigned" not in page


def test_treatment_shows_on_the_patient_page(birads5_patient):
    pid = birads5_patient
    to_report(pid, "Malignant")
    clinician = logged_in("clinician1")
    clinician.post(f"/api/patients/{pid}/result-disclosed", json={"channel": "InPerson"})
    logged_in("navigator1").post(f"/api/patients/{pid}/referral/assign", json={"assignee_staff_id": 8})
    assert clinician.post(f"/api/patients/{pid}/treatment", json={"treatment_type": "Surgery"}).status_code == 200
    page = patient_page()
    assert "Treatment started" in page and "Your surgery started on" in page
    assert "Treatment started: surgery" in page                 # in past visits
