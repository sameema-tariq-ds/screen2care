# screen2care
Creating a process where every urgent screening result is successfully communicated, confirmed by further testing, and converted into medical treatment, with a clear person responsible at every step until the case is officially finished.

FastAPI + PostgreSQL (pgvector) + HTML/CSS dashboard.

## Run it

```bash
docker compose up -d                     # start PostgreSQL (loads db/*.sql on first start)
python -m venv .venv
Windows:   .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

For Docker development with live code, template, and static-file reloads:

```bash
docker compose up --build -d
docker compose logs -f app
```

The production compose command remains `docker compose up --build`.

Open:
- http://localhost:8000          dashboard
- http://localhost:8000/intake   new patient intake form (proforma)
- http://localhost:8000/docs     API docs (Swagger)
- http://localhost:8000/health   health check

## Reset the database

The SQL files only run when the database volume is empty. After changing them:

```bash
docker compose down -v
docker compose up -d
```

## Project layout

```
db/01_schema.sql      tables, indexes, views
db/02_seed.sql        staff, SLA rules, 15 test patients
db/03_intake_form.sql extra columns for the intake form
db/22_risk_assessment.sql post-commit risk result table
app/main.py           FastAPI routes
app/schemas.py        form validation (Pydantic)
app/intake.py         saves the form in one transaction
src/risk_engine.py    pure, versioned first-visit risk calculation
app/database.py       DB connection (reads .env)
app/templates/        HTML (Jinja2)
app/static/           CSS
```

`care_episode`, `sla_task` and `lane_assignment` are empty on purpose: the rules engine (next step) fills them.

The risk migration must be applied before deploying this version. A fresh database
loads it automatically; an existing database should run `db/22_risk_assessment.sql`
once with the application database user.
