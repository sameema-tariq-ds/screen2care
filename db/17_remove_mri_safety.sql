ALTER TABLE patient_risk_profile
    DROP COLUMN IF EXISTS mri_pacemaker,
    DROP COLUMN IF EXISTS mri_pacemaker_status,
    DROP COLUMN IF EXISTS mri_implants,
    DROP COLUMN IF EXISTS mri_implants_status,
    DROP COLUMN IF EXISTS mri_kidney_problems,
    DROP COLUMN IF EXISTS mri_kidney_problems_status;
