ALTER TABLE patient_risk_profile
    DROP COLUMN IF EXISTS hrt_use,
    DROP COLUMN IF EXISTS hrt_duration_years;
