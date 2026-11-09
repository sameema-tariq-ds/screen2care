ALTER TABLE clinical_breast_exam
  ADD COLUMN IF NOT EXISTS nipple_discharge_color VARCHAR(10)
    CHECK (nipple_discharge_color IN ('None','Bloody','Clear','Milky')),
  ADD COLUMN IF NOT EXISTS skin_change VARCHAR(20)
    CHECK (skin_change IN ('Dimpling','Retraction','Scaling / rash'));
