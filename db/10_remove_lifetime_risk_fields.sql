-- Remove lifetime percentage/date/status fields no longer collected by intake.
ALTER TABLE patient_risk_profile
    DROP COLUMN IF EXISTS lifetime_risk_pct,
    DROP COLUMN IF EXISTS lifetime_risk_date,
    DROP COLUMN IF EXISTS lifetime_risk_status;
