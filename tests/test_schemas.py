from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas import IntakeForm
from app.assess import assess
from app.plan_dates import due_dates
from app.schemas import PlanOption


TODAY = date(2026, 11, 7)


def base_payload() -> dict:
    exam = {"inspection": "Normal", "mass": "Normal", "axillary_nodes": "Normal"}
    return {
        "full_name": "Test Patient",
        "date_of_birth": date(1980, 1, 1),
        "patient_id": "BC-TE-001",
        "phone": "+923001234567",
        "evaluation_date": TODAY,
        "presentation": False,
        "marital_status": "Unmarried",
        "chest_radiation": "Unknown",
        "high_risk_biopsy": "None",
        "genetic_status": "Never tested",
        "prior_biopsy_count": 0,
        "prior_biopsy_atypia": "Unknown",
        "personal_breast_cancer": "Unknown",
        "personal_mastectomy": "Unknown",
        "pregnancy_history": "Unknown",
        "breastfeeding_history": "Unknown",
        "height_cm": 170,
        "weight_kg": 65,
        "family_history": [],
        "family_history_none": True,
        "family_history_reviewed": True,
        "cbe_right": exam,
        "cbe_left": exam,
        "imaging": [],
        "imaging_not_done": True,
        "plan": ["Routine rescreening"],
        "examiner_name": "Dr Test",
        "signed_date": TODAY,
    }


def test_no_imaging_yet_is_valid():
    form = IntakeForm(**base_payload())
    assert form.imaging == []


@pytest.mark.parametrize("field", ["height_cm", "weight_kg"])
def test_height_and_weight_are_required(field):
    payload = base_payload() | {"height_cm": 170, "weight_kg": 65}
    payload.pop(field)
    with pytest.raises(ValidationError):
        IntakeForm(**payload)


def test_unmarried_patient_clears_marriage_related_fields():
    form = IntakeForm(**(base_payload() | {
        "parity": 2,
        "age_first_birth": 25,
        "pregnancy_history": "Yes",
        "breastfeeding_history": "Yes",
    }))
    assert form.parity is None
    assert form.age_first_birth is None
    assert form.pregnancy_history.value == "Unknown"
    assert form.breastfeeding_history.value == "Unknown"


def test_empty_birads_is_rejected_when_an_imaging_row_is_present():
    payload = base_payload() | {
        "imaging_not_done": False,
        "imaging": [{
            "date": date(2026, 1, 1),
            "modality": "Mammogram",
            "density": "B",
            "birads": None,
            "radiologist_name": "Dr Reader",
        }],
    }
    with pytest.raises(ValidationError):
        IntakeForm(**payload)


def test_unanswered_presentation_is_rejected():
    payload = base_payload() | {"presentation": None}
    with pytest.raises(ValidationError, match="symptomatic or asymptomatic"):
        IntakeForm(**payload)


def test_hidden_symptom_values_are_cleared_for_asymptomatic_patient():
    payload = base_payload() | {
        "lump_side": "Right",
        "lump_duration": "2 weeks",
        "skin_changes": ["Dimpling"],
        "pain_type": "Cyclical",
        "pain_severity": 5,
    }
    form = IntakeForm(**payload)
    assert form.lump_side is None
    assert form.skin_changes == []
    assert form.pain_type is None


def test_evaluation_date_before_dob_is_rejected():
    payload = base_payload() | {"evaluation_date": date(1979, 12, 31)}
    with pytest.raises(ValidationError, match="before evaluation date"):
        IntakeForm(**payload)


def test_radiation_age_cannot_exceed_current_age():
    payload = base_payload() | {"chest_radiation": "Yes", "chest_radiation_age": 60}
    with pytest.raises(ValidationError, match="Chest-radiation age"):
        IntakeForm(**payload)


def test_future_imaging_date_is_rejected():
    payload = base_payload() | {
        "imaging_not_done": False,
        "imaging": [{
            "date": date(2026, 12, 1),
            "modality": "Mammogram",
            "density": "B",
            "birads": 1,
            "radiologist_name": "Dr Reader",
        }],
    }
    with pytest.raises(ValidationError, match="after the evaluation date"):
        IntakeForm(**payload)


def test_assessment_is_incomplete_when_no_imaging_is_recorded():
    result = assess(IntakeForm(**base_payload()))
    assert result.tier == "Incomplete intake"
    assert result.actionable is True
    assert result.urgency == "Pending"
    assert result.missing == ("Imaging",)


def test_assessment_treats_birads_zero_as_recall_not_missing():
    payload = base_payload() | {
        "imaging_not_done": False,
        "imaging": [{
            "date": date(2026, 1, 1),
            "modality": "Mammogram",
            "density": "B",
            "birads": 0,
            "radiologist_name": "Dr Reader",
        }],
    }
    result = assess(IntakeForm(**payload))
    assert result.tier == "Imaging recall"
    assert result.missing == ()


def test_boundary_age_is_calculated_on_birthday():
    payload = base_payload() | {
        "date_of_birth": date(1951, 11, 7),
    }
    assert IntakeForm(**payload).age == 75


def test_plan_dates_are_deterministic():
    dates = due_dates([PlanOption.ANNUAL_DBT_MRI_6M], TODAY)
    assert dates[PlanOption.ANNUAL_DBT_MRI_6M.value] == date(2027, 5, 8)
