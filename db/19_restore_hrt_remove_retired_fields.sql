-- Restore HRT fields after the earlier temporary removal and retire fields
-- that are no longer collected by the intake form.
ALTER TABLE patient_risk_profile
  ADD COLUMN IF NOT EXISTS hrt_use BOOLEAN,
  ADD COLUMN IF NOT EXISTS hrt_duration_years NUMERIC(4,1);

ALTER TABLE patient_risk_profile
  DROP COLUMN IF EXISTS race_ethnicity,
  DROP COLUMN IF EXISTS carrier_relative_status,
  DROP COLUMN IF EXISTS lifetime_risk_tool;
