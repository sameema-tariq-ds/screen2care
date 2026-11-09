-- Remove fields that are no longer collected by the intake form.
ALTER TABLE patient_risk_profile
    DROP COLUMN IF EXISTS language,
    DROP COLUMN IF EXISTS script;
