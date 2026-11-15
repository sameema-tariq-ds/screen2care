-- =====================================================================
-- Seed data: staff, SLA rules, and the 15 test patients (intake only).
-- care_episode, sla_task and lane_assignment are left EMPTY on purpose:
-- the rules engine must create them. That is how you test the engine.
-- =====================================================================
SET TIME ZONE 'UTC';

-- Staff (IDs 1-10)
INSERT INTO staff (full_name, role) VALUES
 ('Admin Desk',            'Admin'),              -- 1
 ('Dr. Radiologist',       'Radiologist'),        -- 2
 ('Dr. Clinician',         'Clinician'),          -- 3
 ('Dr. Pathologist',       'Pathologist'),        -- 4
 ('Patient Navigator',     'Navigator'),          -- 5
 ('Scheduling Manager',    'SchedulingManager'),  -- 6
 ('Lab Director',          'LabDirector'),        -- 7
 ('Tumor Board',           'TumorBoard'),         -- 8
 ('Chief Medical Officer', 'CMO'),                -- 9
 ('Head of Radiology',     'RadiologyHead');      -- 10

-- SLA rules (your table, with the S2 clock start and 2nd-level escalations added)
INSERT INTO sla_definition
 (section, name, target_hours, clock_start_event, completion_event, escalation1_role, escalation2_role, escalation2_after_hours) VALUES
 (1, 'Critical result notification',  24, 'ResultReleased',     'PatientAcknowledged', 'Navigator',         'Clinician',     48),
 (2, 'Biopsy performed',             168, 'ResultReleased',     'BiopsyPerformed',     'SchedulingManager', 'RadiologyHead', 240),
 (3, 'Pathology report',             120, 'BiopsyPerformed',    'PathologyReported',   'LabDirector',       'CMO',           168),
 (4, 'Oncology referral assigned',   120, 'MalignantConfirmed', 'ReferralAssigned',    'TumorBoard',        'CMO',           168),
 (5, 'Treatment started',            504, 'MalignantConfirmed', 'TreatmentStarted',    'CMO',               NULL,            NULL);

-- Patients
INSERT INTO patient (patient_id, full_name, date_of_birth, national_id, created_by) VALUES
 ('BC-HP-001', 'Sarah Ahmed',    '1981-05-12', '35202-8839211-1', 1),
 ('BC-HP-002', 'Fatima Malik',   '1974-03-22', '35202-9940121-2', 1),
 ('BC-HP-003', 'Ayesha Khan',    '1965-08-19', '35202-1123441-3', 1),
 ('BC-HP-004', 'Zainab Bibi',    '1985-11-30', '35202-4456711-4', 1),
 ('BC-HP-005', 'Mariam Begum',   '1950-04-05', '35202-3349201-5', 1),
 ('BC-DL-006', 'Sana Tariq',     '1978-06-14', '35202-5561231-6', 1),
 ('BC-DL-007', 'Noreen Aslam',   '1971-09-02', '35202-7781291-7', 1),
 ('BC-DL-008', 'Khadija Ali',    '1976-12-12', '35202-2239481-8', 1),
 ('BC-DL-009', 'Hina Shah',      '1983-02-27', '35202-6678231-9', 1),
 ('BC-DL-010', 'Farzana Yasmin', '1959-07-21', '35202-8890122-0', 1),
 ('BC-HR-011', 'Amna Raza',      '1994-10-05', '35202-1122992-1', 1),
 ('BC-HR-012', 'Zohra Bibi',     '1947-01-15', '35202-9930412-2', 1),
 ('BC-HR-013', 'Samina Sheikh',  '1988-05-20', '35202-4471922-3', 1),
 ('BC-HR-014', 'Irum Chaudhry',  '1999-08-14', '35202-1284902-4', 1),
 ('BC-HR-015', 'Amber Jamil',    '1979-03-10', '35202-5541292-5', 1);

-- Risk profiles ("Negative / Unknown" in the source = 'Unknown')
INSERT INTO patient_risk_profile
 (patient_id, menarche_age, menopausal_status, menopause_age, parity, age_first_birth, ocp_use, hrt_use, hrt_duration_years,
  height_cm, weight_kg, genetic_status, genetic_mutation, chest_radiation_age, chest_radiation_note, risk_data_status) VALUES
 ('BC-HP-001', 13, 'Premenopausal',  NULL, 2, 26,   'Past',    false, NULL, 162, 65, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HP-002', 12, 'Perimenopausal', NULL, 3, 24,   'Never',   false, NULL, 158, 70, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HP-003', 14, 'Postmenopausal', 51,   4, 22,   'Never',   true,  3,    160, 68, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HP-004', 12, 'Premenopausal',  NULL, 1, 31,   'Current', false, NULL, 165, 58, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HP-005', 13, 'Postmenopausal', 50,   3, 25,   'Never',   false, NULL, 155, 60, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-DL-006', 12, 'Premenopausal',  NULL, 2, 27,   'Past',    false, NULL, 163, 74, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-DL-007', 14, 'Postmenopausal', 53,   0, NULL, 'Past',    false, NULL, 160, 82, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-DL-008', 13, 'Perimenopausal', NULL, 2, 29,   'Never',   false, NULL, 157, 68, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-DL-009', 11, 'Premenopausal',  NULL, 3, 21,   'Past',    false, NULL, 161, 59, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-DL-010', 14, 'Postmenopausal', 52,   2, 28,   'Never',   false, NULL, 154, 72, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HR-011', 12, 'Premenopausal',  NULL, 0, NULL, 'Current', false, NULL, 166, 55, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HR-012', 15, 'Postmenopausal', 48,   5, 19,   'Never',   false, NULL, 150, 52, 'Unknown',  NULL,    NULL, NULL, 'Pending'),
 ('BC-HR-013', 13, 'Premenopausal',  NULL, 1, 32,   'Never',   false, NULL, 164, 61, 'Unknown',  NULL,    17,   'Mantle field radiation for Hodgkin lymphoma', 'Complete'),
 ('BC-HR-014', 12, 'Premenopausal',  NULL, 0, NULL, 'Past',    false, NULL, 168, 57, 'Positive', 'BRCA1', NULL, NULL, 'Complete'),
 ('BC-HR-015', 13, 'Premenopausal',  NULL, 2, 26,   'Never',   false, NULL, 159, 66, 'Unknown',  NULL,    NULL, NULL, 'Pending');

-- Family history
INSERT INTO family_history (patient_id, relation, relation_degree, cancer_type, age_at_diagnosis) VALUES
 ('BC-DL-006', 'Mother',        1,    'Breast',  55),
 ('BC-DL-007', 'Maternal Aunt', 2,    'Breast',  60),
 ('BC-DL-008', 'Sister',        1,    'Breast',  47),
 ('BC-DL-010', 'Mother',        1,    'Breast',  62),
 ('BC-DL-010', 'Maternal Aunt', 2,    'Breast',  58),
 ('BC-DL-010', 'Unspecified',   NULL, 'Ovarian', NULL),   -- source says "Ovarian: Yes" without naming the relative
 ('BC-HR-014', 'Mother',        1,    'Breast',  42);

-- Prior breast procedures (none are ADH/ALH/LCIS)
INSERT INTO prior_breast_procedure (patient_id, procedure_type, laterality, procedure_year, result_summary) VALUES
 ('BC-HP-004', 'CystAspiration', 'R', 2022, 'Benign fluid'),
 ('BC-DL-007', 'Biopsy',         'L', 2015, 'Benign fibroadenoma'),
 ('BC-HR-015', 'CystAspiration', 'R', 2021, 'Benign cyst aspiration');

-- Comorbidities (HR-012: moved out of the breast-history field)
INSERT INTO comorbidity (patient_id, description, is_severe_active, recorded_at) VALUES
 ('BC-HR-012', 'Stage IV congestive heart failure', true, '2026-11-05'),
 ('BC-HR-012', 'End-stage renal disease (ESRD)',    true, '2026-11-05');

-- Encounters (explicit IDs 1-15 so later inserts can reference them)
INSERT INTO encounter
 (encounter_id, patient_id, encounter_date, encounter_type, is_symptomatic, chief_complaint, symptom_duration_days, clinician_id, entered_by) VALUES
 (1,  'BC-HP-001', '2026-10-01 09:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (2,  'BC-HP-002', '2026-10-01 09:30', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (3,  'BC-HP-003', '2026-10-01 10:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (4,  'BC-HP-004', '2026-10-01 10:30', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (5,  'BC-HP-005', '2026-10-01 11:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (6,  'BC-DL-006', '2026-11-03 09:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (7,  'BC-DL-007', '2026-10-20 09:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (8,  'BC-DL-008', '2026-10-25 09:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (9,  'BC-DL-009', '2026-10-15 09:00', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (10, 'BC-DL-010', '2026-10-01 11:30', 'Screening',            false, 'Asymptomatic (Routine Screening)',           NULL, 3, 1),
 (11, 'BC-HR-011', '2026-11-05 09:00', 'Diagnostic',           true,  'Lump / mass: left breast',                   21,   3, 1),
 (12, 'BC-HR-012', '2026-11-05 09:30', 'Screening',            false, 'Asymptomatic (Patient Requested Screening)', NULL, 3, 1),
 (13, 'BC-HR-013', '2026-11-05 10:00', 'HighRiskSurveillance', false, 'Asymptomatic (High-Risk Surveillance Path)', NULL, 3, 1),
 (14, 'BC-HR-014', '2026-11-05 10:30', 'HighRiskSurveillance', false, 'Asymptomatic (Early Risk Evaluation Tier)',  NULL, 3, 1),
 (15, 'BC-HR-015', '2026-10-25 10:00', 'Diagnostic',           true,  'Lump / mass: right breast',                  30,   3, 1);
-- Move the ID counter past the explicit IDs
SELECT setval(pg_get_serial_sequence('encounter', 'encounter_id'), (SELECT MAX(encounter_id) FROM encounter));

INSERT INTO geriatric_assessment (encounter_id, end_stage_organ_failure_or_dementia, independent_in_adl, life_expectancy_over_10y) VALUES
 (5,  false, true,  NULL),   -- HP-005: clinician still needs to confirm life expectancy
 (12, true,  false, false);  -- HR-012: life expectancy < 3 years per disposition

-- Clinical breast exam (one row per side)
INSERT INTO clinical_breast_exam
 (encounter_id, laterality, inspection_normal, inspection_finding, mass_present, mass_size_mm, mass_mobility, axillary_node_palpable) VALUES
 (1,  'R', true,  NULL,                             false, NULL, NULL,     false), (1,  'L', true, NULL, true,  12,   'Mobile', false),
 (2,  'R', true,  NULL,                             false, NULL, NULL,     false), (2,  'L', true, NULL, false, NULL, NULL,     false),
 (3,  'R', false, 'Subtle retroareolar flattening', true,  18,   'Fixed',  true),  (3,  'L', true, NULL, false, NULL, NULL,     false),
 (4,  'R', true,  NULL,                             false, NULL, NULL,     false), (4,  'L', true, NULL, false, NULL, NULL,     false),
 (5,  'R', true,  NULL,                             false, NULL, NULL,     false), (5,  'L', true, NULL, true,  8,    'Mobile', false),
 (6,  'R', true,  NULL,                             false, NULL, NULL,     false), (6,  'L', false, 'Mild skin dimpling',     true, 14, 'Fixed', false),
 (7,  'R', false, 'Nipple retraction',              true,  22,   'Fixed',  true),  (7,  'L', true, NULL, false, NULL, NULL,     false),
 (8,  'R', true,  NULL,                             false, NULL, NULL,     false), (8,  'L', true, NULL, false, NULL, NULL,     false),
 (9,  'R', true,  NULL,                             false, NULL, NULL,     false), (9,  'L', true, NULL, true,  15,   'Fixed',  false),
 (10, 'R', false, 'Scaling on skin',                true,  25,   'Fixed',  true),  (10, 'L', true, NULL, false, NULL, NULL,     false),
 (11, 'R', true,  NULL,                             false, NULL, NULL,     false), (11, 'L', false, 'Visible contours/bulge', true, 30, 'Fixed', true),
 (12, 'R', true,  NULL,                             false, NULL, NULL,     false), (12, 'L', true, NULL, false, NULL, NULL,     false),
 (13, 'R', true,  NULL,                             false, NULL, NULL,     false), (13, 'L', true, NULL, false, NULL, NULL,     false),
 (14, 'R', true,  NULL,                             false, NULL, NULL,     false), (14, 'L', true, NULL, false, NULL, NULL,     false),
 (15, 'R', false, 'Skin retraction',                true,  28,   'Fixed',  true),  (15, 'L', true, NULL, false, NULL, NULL,     false);

-- Imaging results (input for the Step 3 matrix)
INSERT INTO imaging_result
 (encounter_id, patient_id, modality, laterality, birads_category, density, result_released_at, radiologist_id, report_text) VALUES
 (1,  'BC-HP-001', 'Mammogram',  'B', 4, 'B',  '2026-10-01 14:00', 2, NULL),
 (2,  'BC-HP-002', 'Mammogram',  'B', 4, 'A',  '2026-10-01 14:00', 2, NULL),
 (3,  'BC-HP-003', 'DBT',        'B', 5, 'B',  '2026-10-01 14:00', 2, NULL),
 (4,  'BC-HP-004', 'Mammogram',  'B', 1, 'D',  '2026-10-01 14:00', 2, NULL),
 (5,  'BC-HP-005', 'Mammogram',  'B', 4, 'B',  '2026-10-01 14:00', 2, NULL),
 (6,  'BC-DL-006', 'Mammogram',  'B', 4, 'C',  '2026-11-03 14:00', 2, NULL),
 (7,  'BC-DL-007', 'Mammogram',  'B', 5, 'C',  '2026-10-20 14:00', 2, NULL),
 (8,  'BC-DL-008', 'Mammogram',  'B', 4, 'B',  '2026-10-25 14:00', 2, 'Calcifications only visible on imaging'),
 (9,  'BC-DL-009', 'Mammogram',  'B', 4, 'B',  '2026-10-15 14:00', 2, NULL),
 (10, 'BC-DL-010', 'Mammogram',  'B', 5, 'C',  '2026-10-01 14:00', 2, NULL),
 (11, 'BC-HR-011', 'Mammogram',  'B', 5, 'D',  '2026-11-05 14:00', 2, NULL),
 (11, 'BC-HR-011', 'Ultrasound', 'L', 5, NULL, '2026-11-05 14:00', 2, NULL),
 (12, 'BC-HR-012', 'Mammogram',  'B', 2, 'A',  '2026-11-05 14:00', 2, NULL),
 (13, 'BC-HR-013', 'DBT',        'B', 1, 'C',  '2026-11-05 14:00', 2, NULL),
 (14, 'BC-HR-014', 'MRI',        'B', 1, NULL, '2026-11-05 14:00', 2, 'Source listed density D; MRI reports fibroglandular tissue amount instead'),
 (15, 'BC-HR-015', 'Mammogram',  'B', 5, 'C',  '2026-10-25 14:00', 2, NULL);

-- Disposition notes, kept as written in the source (not released to the patient)
INSERT INTO clinical_note (encounter_id, author_id, note_type, note_text) VALUES
 (1,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (2,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (3,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (4,  3, 'Disposition', 'Routine rescreening in 1-2 years (triggers supplemental ABUS due to category D density)'),
 (5,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (6,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (7,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (8,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (stereotactic core biopsy)'),
 (9,  3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (10, 3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (11, 3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy)'),
 (12, 3, 'Disposition', 'Routine rescreening in 1-2 years (prompt generated to drop future screening via shared-decision encounter due to life expectancy <3 years)'),
 (13, 3, 'Disposition', 'Short-term diagnostic follow-up (transitions directly to NCCN high-risk path: annual DBT alternating with annual breast MRI every 6 months)'),
 (14, 3, 'Disposition', 'Routine rescreening in 1-2 years (mandated for annual breast MRI protocol due to age and BRCA1 mutation status)'),
 (15, 3, 'Disposition', 'Urgent referral for interventional tissue diagnosis (core needle biopsy - pathology text records triple-negative breast cancer phenotype, Ki-67 at 85%)');
