import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://loop:loop_dev_password@localhost:5432/screening_care_loop",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def ensure_runtime_schema() -> None:
    """Apply small, idempotent schema additions needed by the running app.

    Docker's init scripts only run when the PostgreSQL data volume is created.
    Existing volumes therefore need runtime-safe migrations as the application
    evolves.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE family_history
            ADD COLUMN IF NOT EXISTS known_genetic_mutations VARCHAR(8)
                NOT NULL DEFAULT 'Unknown'
        """))
        conn.execute(text("""
            ALTER TABLE family_history
            DROP CONSTRAINT IF EXISTS family_history_known_genetic_mutations_check
        """))
        conn.execute(text("""
            ALTER TABLE family_history
            ADD CONSTRAINT family_history_known_genetic_mutations_check
            CHECK (known_genetic_mutations IN ('BRCA1','BRCA2','Negative','Unknown'))
        """))
        conn.execute(text("""
            ALTER TABLE patient_risk_profile
            ADD COLUMN IF NOT EXISTS breastfeeding_duration_years NUMERIC(4,1)
        """))
