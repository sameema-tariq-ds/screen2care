-- Runtime-safe additions for already-initialised databases.
ALTER TABLE encounter ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);
CREATE UNIQUE INDEX IF NOT EXISTS ux_encounter_idempotency_key
    ON encounter(idempotency_key) WHERE idempotency_key IS NOT NULL;
ALTER TABLE patient_risk_profile ADD COLUMN IF NOT EXISTS carrier_relative_status VARCHAR(10)
    CHECK (carrier_relative_status IN ('Yes', 'No', 'Unknown'));

