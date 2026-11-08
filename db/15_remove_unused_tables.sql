-- Keep only tables used by the current intake, assessment and dashboard flows.
DROP VIEW IF EXISTS vw_sla_status;
DROP VIEW IF EXISTS vw_patient_released_notes;

DROP TABLE IF EXISTS pathology_result CASCADE;
DROP TABLE IF EXISTS biopsy CASCADE;
DROP TABLE IF EXISTS treatment CASCADE;
DROP TABLE IF EXISTS sla_task CASCADE;
DROP TABLE IF EXISTS sla_definition CASCADE;
DROP TABLE IF EXISTS patient_contact CASCADE;
DROP TABLE IF EXISTS referral CASCADE;
DROP TABLE IF EXISTS lane_assignment CASCADE;
DROP TABLE IF EXISTS clinical_note CASCADE;
DROP TABLE IF EXISTS care_episode CASCADE;
DROP TABLE IF EXISTS comorbidity CASCADE;
DROP TABLE IF EXISTS geriatric_assessment CASCADE;
DROP TABLE IF EXISTS staff CASCADE;

DROP INDEX IF EXISTS ux_patient_national_id;
ALTER TABLE patient
    DROP COLUMN IF EXISTS national_id,
    DROP COLUMN IF EXISTS created_by,
    DROP COLUMN IF EXISTS created_by_name;

ALTER TABLE encounter
    DROP COLUMN IF EXISTS geriatric_life_expectancy_over_10y,
    DROP COLUMN IF EXISTS geriatric_serious_medical_conditions,
    DROP COLUMN IF EXISTS geriatric_end_stage_organ_failure_or_dementia,
    DROP COLUMN IF EXISTS geriatric_independent_in_adls;
