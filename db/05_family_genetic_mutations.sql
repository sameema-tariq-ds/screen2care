-- Family-history genetic mutation status for existing databases.
ALTER TABLE family_history
    ADD COLUMN IF NOT EXISTS known_genetic_mutations VARCHAR(8) NOT NULL DEFAULT 'Unknown';

ALTER TABLE family_history
    DROP CONSTRAINT IF EXISTS family_history_known_genetic_mutations_check;

ALTER TABLE family_history
    ADD CONSTRAINT family_history_known_genetic_mutations_check
      CHECK (known_genetic_mutations IN ('BRCA1','BRCA2','Negative','Unknown'));
