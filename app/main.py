from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.database import engine
from app.assess import assess
from app.intake import save_intake
from app.schemas import IntakeForm

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Screening-to-Care Loop")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Latest imaging result per patient (highest BI-RADS wins; a mammogram with density beats US/MRI)
PATIENT_LIST_SQL = text("""
    SELECT p.patient_id,
           p.full_name,
           date_part('year', age(p.date_of_birth))::int AS age,
           img.birads_category,
           img.density,
           img.result_released_at,
           (SELECT COUNT(*) FROM vw_data_quality_flags f WHERE f.patient_id = p.patient_id) AS flag_count
    FROM patient p
    LEFT JOIN LATERAL (
        SELECT i.birads_category, i.density, i.result_released_at
        FROM imaging_result i
        WHERE i.patient_id = p.patient_id
        ORDER BY i.result_released_at DESC, i.birads_category DESC, (i.density IS NULL)
        LIMIT 1
    ) img ON TRUE
    ORDER BY p.patient_id
""")


def fetch_patients():
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(PATIENT_LIST_SQL)]


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/patients")
def list_patients():
    return fetch_patients()


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str):
    with engine.connect() as conn:
        patient = conn.execute(
            text("SELECT * FROM patient WHERE patient_id = :pid"), {"pid": patient_id}
        ).mappings().first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")

        def rows(sql):
            return [dict(r) for r in conn.execute(text(sql), {"pid": patient_id}).mappings()]

        return {
            "patient": {k: v for k, v in patient.items() if k != "national_id"},
            "risk_profile": rows("SELECT * FROM patient_risk_profile WHERE patient_id = :pid"),
            "family_history": rows("SELECT * FROM family_history WHERE patient_id = :pid"),
            "encounters": rows("SELECT * FROM encounter WHERE patient_id = :pid ORDER BY encounter_date"),
            "imaging": rows("SELECT * FROM imaging_result WHERE patient_id = :pid ORDER BY result_released_at"),
            "flags": rows("SELECT flag FROM vw_data_quality_flags WHERE patient_id = :pid"),
        }


@app.get("/api/data-quality-flags")
def data_quality_flags():
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            text("SELECT * FROM vw_data_quality_flags ORDER BY patient_id")
        ).mappings()]


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"patients": fetch_patients()})


@app.get("/intake", response_class=HTMLResponse)
def intake_form(request: Request):
    return templates.TemplateResponse(request, "intake.html", {})


@app.post("/api/intake", status_code=201)
def submit_intake(form: IntakeForm):
    return save_intake(form)


@app.post("/api/intake/preview")
def preview_intake(form: IntakeForm):
    """Validate and assess without writing patient, encounter, or audit data."""
    result = assess(form)
    return {"assessment": result.as_dict(), "warnings": form.warnings(), "age": form.age, "bmi": form.bmi}
