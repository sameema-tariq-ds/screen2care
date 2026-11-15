# The navigator books only the biopsy appointment (date and time), no biopsy type.
from app.rules_runner import run_engine
from tests.test_sla import PATIENT_LOGIN, PID, birads5_patient, logged_in, sql  # noqa: F401  (fixture)


def test_navigator_books_date_and_time_only(birads5_patient):
    run_engine(PID)
    nav = logged_in("navigator1")
    page = nav.get(f"/loop/{PID}").text
    assert "Book the biopsy appointment" not in page and 'name="biopsy_type"' not in page
    assert nav.post(f"/api/patients/{PID}/biopsy",
                    json={"scheduled_for": "2030-01-01T09:00"}).status_code == 409
    assert logged_in(PATIENT_LOGIN).post("/api/me/acknowledge").status_code == 200
    page = nav.get(f"/loop/{PID}").text
    assert "Book the biopsy appointment" in page
    assert nav.post(f"/api/patients/{PID}/biopsy", json={}).status_code == 422          # date is required
    assert nav.post(f"/api/patients/{PID}/biopsy", json={"scheduled_for": "2030-01-01T09:00"}).status_code == 200
    b = sql("""SELECT b.* FROM biopsy b JOIN care_episode e USING (episode_id) WHERE e.patient_id = :p""",
            p=PID).mappings().one()
    assert b["status"] == "Booked" and b["biopsy_type"] is None and b["booked_by"] == 5
    assert "booked by" in nav.get(f"/loop/{PID}").text
    assert nav.post(f"/api/patients/{PID}/biopsy", json={"scheduled_for": "2030-01-02T09:00"}).status_code == 409
