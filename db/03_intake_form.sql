-- =====================================================================
-- Additions for the Breast Screening Clinical Proforma (intake form)
-- Runs after 01_schema.sql and 02_seed.sql on first database start.
-- =====================================================================

-- Section 2 (symptoms) and Section 7 (plan, signature) live on the encounter
ALTER TABLE encounter
    ADD COLUMN lump_side               VARCHAR(5)  CHECK (lump_side IN ('Right','Left','Both')),
    ADD COLUMN lump_duration           VARCHAR(50),
    ADD COLUMN nipple_discharge_side   VARCHAR(5)  CHECK (nipple_discharge_side IN ('Right','Left','Both')),
    ADD COLUMN nipple_discharge_color  VARCHAR(6)  CHECK (nipple_discharge_color IN ('Bloody','Clear','Milky')),
    ADD COLUMN skin_changes            TEXT[],
    ADD COLUMN pain_type               VARCHAR(12) CHECK (pain_type IN ('Cyclical','Non-cyclical')),
    ADD COLUMN pain_severity           SMALLINT    CHECK (pain_severity BETWEEN 1 AND 10),
    ADD COLUMN disposition             VARCHAR(25) CHECK (disposition IN ('RoutineRescreen','ShortTermFollowUp','UrgentBiopsyReferral')),
    ADD COLUMN followup_months         SMALLINT    CHECK (followup_months BETWEEN 1 AND 24),
    ADD COLUMN examiner_name           VARCHAR(150),
    ADD COLUMN signed_date             DATE;

-- Section 4: the form also lists lumpectomy and implants
ALTER TABLE prior_breast_procedure DROP CONSTRAINT prior_breast_procedure_procedure_type_check;
ALTER TABLE prior_breast_procedure ADD CONSTRAINT prior_breast_procedure_procedure_type_check
    CHECK (procedure_type IN ('CystAspiration','Biopsy','Lumpectomy','Implants','Surgery','Other'));

-- Section 5: mass consistency
ALTER TABLE clinical_breast_exam
    ADD COLUMN mass_consistency VARCHAR(5) CHECK (mass_consistency IN ('Soft','Firm','Hard'));

-- Patient IDs for new patients: BC-00001, BC-00002, ...
CREATE SEQUENCE patient_number_seq START 1;

-- Required intake identity/contact data. Seed data gets a deterministic placeholder
-- phone before this constraint is applied; real records must contain a patient phone.
UPDATE patient SET phone = '+920000000000' WHERE phone IS NULL;
ALTER TABLE patient ALTER COLUMN national_id SET NOT NULL;
ALTER TABLE patient ALTER COLUMN phone SET NOT NULL;

ALTER TABLE patient_risk_profile
    DROP CONSTRAINT IF EXISTS patient_risk_profile_genetic_status_check,
    ALTER COLUMN genetic_status TYPE VARCHAR(20),
    ADD COLUMN race_ethnicity VARCHAR(80),
    ADD COLUMN chest_radiation_status VARCHAR(8) CHECK (chest_radiation_status IN ('Yes','No','Unknown')),
    ADD COLUMN chest_radiation_years SMALLINT CHECK (chest_radiation_years BETWEEN 0 AND 100),
    ADD COLUMN high_risk_biopsy VARCHAR(7) CHECK (high_risk_biopsy IN ('None','ADH','ALH','LCIS','Unknown')),
    ADD COLUMN lifetime_risk_tool VARCHAR(50),
    ADD COLUMN lifetime_risk_date DATE,
    ADD COLUMN lifetime_risk_status VARCHAR(9) CHECK (lifetime_risk_status IN ('Done','Not done','Pending')),
    ADD COLUMN prior_biopsy_count SMALLINT CHECK (prior_biopsy_count BETWEEN 0 AND 100),
    ADD COLUMN prior_biopsy_atypia VARCHAR(8) CHECK (prior_biopsy_atypia IN ('Yes','No','Unknown')),
    ADD COLUMN personal_breast_cancer BOOLEAN,
    ADD COLUMN personal_breast_cancer_status VARCHAR(7) CHECK (personal_breast_cancer_status IN ('Yes','No','Unknown')),
    ADD COLUMN personal_mastectomy BOOLEAN,
    ADD COLUMN personal_mastectomy_status VARCHAR(7) CHECK (personal_mastectomy_status IN ('Yes','No','Unknown')),
    ADD COLUMN pregnancy_history BOOLEAN,
    ADD COLUMN pregnancy_history_status VARCHAR(7) CHECK (pregnancy_history_status IN ('Yes','No','Unknown')),
    ADD COLUMN breastfeeding_history BOOLEAN,
    ADD COLUMN breastfeeding_history_status VARCHAR(7) CHECK (breastfeeding_history_status IN ('Yes','No','Unknown')),
    ADD COLUMN mri_pacemaker BOOLEAN,
    ADD COLUMN mri_pacemaker_status VARCHAR(7) CHECK (mri_pacemaker_status IN ('Yes','No','Unknown')),
    ADD COLUMN mri_implants BOOLEAN,
    ADD COLUMN mri_implants_status VARCHAR(7) CHECK (mri_implants_status IN ('Yes','No','Unknown')),
    ADD COLUMN mri_kidney_problems BOOLEAN,
    ADD COLUMN mri_kidney_problems_status VARCHAR(7) CHECK (mri_kidney_problems_status IN ('Yes','No','Unknown')),
    ADD CONSTRAINT patient_risk_profile_genetic_status_check CHECK
      (genetic_status IN ('Positive','Negative','Unknown','Pending','Never tested'));

ALTER TABLE family_history ADD COLUMN IF NOT EXISTS family_side VARCHAR(20)
    CHECK (family_side IN ('Mother''s side','Father''s side','Unknown side'));

ALTER TABLE encounter
    ADD COLUMN IF NOT EXISTS plan_options TEXT[],
    ADD COLUMN IF NOT EXISTS warning_override_reason VARCHAR(400),
    ADD COLUMN IF NOT EXISTS notified_person VARCHAR(150),
    ADD COLUMN IF NOT EXISTS notified_at DATE,
    ADD COLUMN IF NOT EXISTS patient_reached BOOLEAN,
    ADD COLUMN IF NOT EXISTS biopsy_followup_result VARCHAR(10)
      CHECK (biopsy_followup_result IN ('Benign','ADH/LCIS','Cancer')),
    ADD COLUMN IF NOT EXISTS biopsy_followup_date DATE,
    ADD COLUMN IF NOT EXISTS geriatric_life_expectancy_over_10y BOOLEAN,
    ADD COLUMN IF NOT EXISTS geriatric_serious_medical_conditions BOOLEAN;

ALTER TABLE clinical_breast_exam
    ADD COLUMN IF NOT EXISTS inspection_status VARCHAR(12)
      CHECK (inspection_status IN ('Not answered','Normal','Abnormal')),
    ADD COLUMN IF NOT EXISTS mass_status VARCHAR(12)
      CHECK (mass_status IN ('Not answered','Normal','Abnormal')),
    ADD COLUMN IF NOT EXISTS axillary_node_status VARCHAR(12)
      CHECK (axillary_node_status IN ('Not answered','Normal','Abnormal'));

ALTER TABLE imaging_result
    ADD COLUMN IF NOT EXISTS performed_date DATE,
    ADD COLUMN IF NOT EXISTS radiologist_name VARCHAR(150);
