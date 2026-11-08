from src.risk_engine import calculate_risk


def snapshot(**values):
    base = {
        "age": 45,
        "genetic_status": "Negative",
        "chest_radiation": "No",
        "high_risk_biopsy": "None",
        "family_history": [],
        "imaging_not_done": False,
        "imaging": [{"date": "2026-01-01", "modality": "Mammogram", "density": "B", "birads": 1}],
    }
    base.update(values)
    return {"submitted": base}


def test_genetic_high_risk_is_first_and_explained():
    result = calculate_risk(snapshot(genetic_status="Positive", genetic_gene="BRCA1"))
    assert result.tier == "High"
    assert result.reasons == ("genetic_status = Positive (BRCA1).",)


def test_multiple_high_risk_factors_are_returned():
    result = calculate_risk(snapshot(
        chest_radiation="Yes", chest_radiation_age=22,
        high_risk_biopsy="LCIS",
    ))
    assert result.tier == "High"
    assert result.reasons == (
        "chest_radiation = Yes; chest_radiation_age = 22.",
        "high_risk_biopsy = LCIS.",
    )


def test_medium_density_and_birads_are_explained():
    result = calculate_risk(snapshot(
        imaging=[{"date": "2026-01-01", "modality": "Mammogram", "density": "C", "birads": 3}],
    ))
    assert result.tier == "Medium"
    assert len(result.reasons) == 2


def test_low_label_is_explicit_about_lifetime_risk():
    result = calculate_risk(snapshot())
    assert result.label == "Low (lifetime risk not assessed)"


def test_missing_imaging_is_incomplete():
    result = calculate_risk(snapshot(imaging=[], imaging_not_done=True))
    assert result.tier == "Incomplete"
