-- Demographic-only import. Phone numbers are fictional placeholders.
DROP INDEX IF EXISTS ux_patient_national_id;
ALTER TABLE patient
    DROP COLUMN IF EXISTS national_id,
    DROP COLUMN IF EXISTS created_by,
    DROP COLUMN IF EXISTS created_by_name;

INSERT INTO patient (patient_id, full_name, date_of_birth, phone)
VALUES
 ('BC-HP-001', 'Sarah Ahmed',    '1981-05-12', '03018452716'),
 ('BC-HP-002', 'Fatima Malik',   '1974-03-22', '03026719348'),
 ('BC-HP-003', 'Ayesha Khan',    '1965-08-19', '03034928165'),
 ('BC-HP-004', 'Zainab Bibi',    '1985-11-30', '03047582039'),
 ('BC-HP-005', 'Mariam Begum',   '1950-05-04', '03053169472'),
 ('BC-DL-006', 'Sana Tariq',     '1978-06-14', '03068294517'),
 ('BC-DL-007', 'Noreen Aslam',   '1971-09-02', '03075746803'),
 ('BC-DL-008', 'Khadija Ali',    '1976-12-12', '03082637951'),
 ('BC-DL-009', 'Hina Shah',      '1983-02-27', '03099183642'),
 ('BC-DL-010', 'Farzana Yasmin', '1959-07-21', '03104478296'),
 ('BC-HR-011', 'Amna Raza',      '1994-10-05', '03117051384'),
 ('BC-HR-012', 'Zohra Bibi',     '1947-01-15', '03123869470'),
 ('BC-HR-013', 'Samina Sheikh',  '1988-05-20', '03136527048'),
 ('BC-HR-014', 'Irum Chaudhry',  '1999-08-14', '03148192365'),
 ('BC-HR-015', 'Amber Jamil',    '1979-03-10', '03152748631')
ON CONFLICT (patient_id) DO UPDATE SET
    full_name = EXCLUDED.full_name,
    date_of_birth = EXCLUDED.date_of_birth,
    phone = EXCLUDED.phone;
