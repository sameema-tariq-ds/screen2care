-- Idempotent migration for databases created before the expanded intake form.
-- Safe to run against an existing development database.

CREATE SEQUENCE IF NOT EXISTS patient_number_seq START 1;

UPDATE patient SET phone = '+920000000000' WHERE phone IS NULL;
UPDATE patient SET national_id = 'MIGRATED-' || patient_id WHERE national_id IS NULL;
ALTER TABLE patient ALTER COLUMN national_id SET NOT NULL;
ALTER TABLE patient ALTER COLUMN phone SET NOT NULL;

ALTER TABLE patient_risk_profile
    DROP CONSTRAINT IF EXISTS patient_risk_profile_genetic_status_check,
    ALTER COLUMN genetic_status TYPE VARCHAR(20),
    ADD COLUMN IF NOT EXISTS race_ethnicity VARCHAR(80),
    ADD COLUMN IF NOT EXISTS chest_radiation_status VARCHAR(8),
    ADD COLUMN IF NOT EXISTS chest_radiation_years SMALLINT,
    ADD COLUMN IF NOT EXISTS high_risk_biopsy VARCHAR(7),
    ADD COLUMN IF NOT EXISTS lifetime_risk_tool VARCHAR(50),
    ADD COLUMN IF NOT EXISTS lifetime_risk_date DATE,
    ADD COLUMN IF NOT EXISTS lifetime_risk_status VARCHAR(9),
    ADD COLUMN IF NOT EXISTS prior_biopsy_count SMALLINT,
    ADD COLUMN IF NOT EXISTS prior_biopsy_atypia VARCHAR(8),
    ADD COLUMN IF NOT EXISTS personal_breast_cancer BOOLEAN,
    ADD COLUMN IF NOT EXISTS personal_breast_cancer_status VARCHAR(7),
    ADD COLUMN IF NOT EXISTS personal_mastectomy BOOLEAN,
    ADD COLUMN IF NOT EXISTS personal_mastectomy_status VARCHAR(7),
    ADD COLUMN IF NOT EXISTS pregnancy_history BOOLEAN,
    ADD COLUMN IF NOT EXISTS pregnancy_history_status VARCHAR(7),
    ADD COLUMN IF NOT EXISTS breastfeeding_history BOOLEAN,
    ADD COLUMN IF NOT EXISTS breastfeeding_history_status VARCHAR(7),
    ADD COLUMN IF NOT EXISTS mri_pacemaker BOOLEAN,
    ADD COLUMN IF NOT EXISTS mri_pacemaker_status VARCHAR(7),
    ADD COLUMN IF NOT EXISTS mri_implants BOOLEAN,
    ADD COLUMN IF NOT EXISTS mri_implants_status VARCHAR(7),
    ADD COLUMN IF NOT EXISTS mri_kidney_problems BOOLEAN,
    ADD COLUMN IF NOT EXISTS mri_kidney_problems_status VARCHAR(7),
    ADD CONSTRAINT patient_risk_profile_genetic_status_check CHECK
      (genetic_status IN ('Positive','Negative','Unknown','Pending','Never tested'));

ALTER TABLE family_history ADD COLUMN IF NOT EXISTS family_side VARCHAR(20);

ALTER TABLE encounter
    ADD COLUMN IF NOT EXISTS plan_options TEXT[],
    ADD COLUMN IF NOT EXISTS warning_override_reason VARCHAR(400),
    ADD COLUMN IF NOT EXISTS notified_person VARCHAR(150),
    ADD COLUMN IF NOT EXISTS notified_at DATE,
    ADD COLUMN IF NOT EXISTS patient_reached BOOLEAN,
    ADD COLUMN IF NOT EXISTS biopsy_followup_result VARCHAR(10),
    ADD COLUMN IF NOT EXISTS biopsy_followup_date DATE,
    ADD COLUMN IF NOT EXISTS geriatric_life_expectancy_over_10y BOOLEAN,
    ADD COLUMN IF NOT EXISTS geriatric_serious_medical_conditions BOOLEAN;

ALTER TABLE clinical_breast_exam
    ADD COLUMN IF NOT EXISTS inspection_status VARCHAR(12),
    ADD COLUMN IF NOT EXISTS mass_status VARCHAR(12),
    ADD COLUMN IF NOT EXISTS axillary_node_status VARCHAR(12);

ALTER TABLE imaging_result
    ADD COLUMN IF NOT EXISTS performed_date DATE,
    ADD COLUMN IF NOT EXISTS radiologist_name VARCHAR(150);
