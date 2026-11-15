# Screening-to-Care Loop

A web app for a breast-screening clinic. It follows every patient from the front desk to the end of
their care, so that nobody with an abnormal result is lost on the way:

- **Registration** at the front desk, then a **clinical intake** by the doctor.
- A **rules engine** decides each patient's screening lane: routine, high risk, dense breast,
  6-month check, urgent and others.
- A **care loop** for suspicious results (BI-RADS 4/5): result notification, biopsy, pathology,
  oncology referral and treatment. Each step has a deadline (SLA). A missed deadline sends an alert
  to the role that must act.
- A separate **imaging follow-up loop** for patients whose next step is another scan: BI-RADS 0 recall,
  BI-RADS 3 six-month scan, annual, dense and high-risk screening, and the check scan after a benign biopsy.
- A **patient portal**: patients see their own progress and appointments. They see a biopsy result
  only after a doctor has discussed it with them.
- **Local AI** (Ollama, free, runs on the laptop): drafts patient notes and call scripts, and answers
  staff questions about their own patients. A person always reviews the output.

Stack: FastAPI (Python), PostgreSQL 16 with pgvector in Docker, server-rendered HTML (Jinja2), JWT login in a cookie, pytest.

---

## Contents

1. [Quick start](#1-quick-start)
2. [Daily use and updating](#2-daily-use-and-updating)
3. [Configuration (.env)](#3-configuration-env)
4. [Logins and what each role sees](#4-logins-and-what-each-role-sees)
5. [The whole patient journey](#5-the-whole-patient-journey)
6. [Registration and clinical intake](#6-registration-and-clinical-intake)
7. [The rules engine (screening lanes)](#7-the-rules-engine-screening-lanes)
8. [Care loop for BI-RADS 4/5 (S1–S5)](#8-care-loop-for-bi-rads-45-s1s5)
9. [Imaging follow-up loop (R1–R4)](#9-imaging-follow-up-loop-r1r4)
10. [Closing a loop and restarting it](#10-closing-a-loop-and-restarting-it)
11. [Deadlines, alerts and escalation](#11-deadlines-alerts-and-escalation)
12. [Dashboards](#12-dashboards)
13. [Patient portal](#13-patient-portal)
14. [Clinical plan page and patient notes](#14-clinical-plan-page-and-patient-notes)
15. [Sign-up and accounts](#15-sign-up-and-accounts)
16. [Local AI](#16-local-ai)
17. [Data-quality flags](#17-data-quality-flags)
18. [Database](#18-database)
19. [Code layout](#19-code-layout)
20. [API reference](#20-api-reference)
21. [Tests](#21-tests)
22. [Troubleshooting](#22-troubleshooting)
23. [Known limitations](#23-known-limitations)

---

## 1. Quick start

You need: **Docker Desktop**, **Python 3.11+** (developed on 3.13), **Git**, and Bash
(Git Bash on Windows, WSL, or a macOS/Linux terminal). Ollama is optional (only for the AI features).

```bash
git clone https://github.com/sameema-tariq-ds/screen2care.git
cd screen2care
git checkout javaria/care-loop-system

bash main.sh                              # performs setup and starts the app
```

Open http://localhost:8000 and log in, for example as `admin1` / `Dev@12345`.

| Address | What it is |
|---|---|
| http://localhost:8000 | Dashboard (each role sees its own) |
| http://localhost:8000/register | Front desk: register a patient (Admin) |
| http://localhost:8000/intake | Clinical proforma (Clinician) |
| http://localhost:8000/loop/BC-HP-001 | Care loop of one patient |
| http://localhost:8000/followup/BC-HP-004 | Imaging follow-up of one patient |
| http://localhost:8000/signup | Patient and staff sign-up |
| http://localhost:8000/docs | Every API endpoint (Swagger) |
| http://localhost:8000/health | Health check |

`main.sh` waits for PostgreSQL, applies the current migrations, creates the virtual environment,
installs dependencies from `pyproject.toml`, seeds the test logins, runs the rules engine, and
starts the app. The command should end with `Done. Dev password is Dev@12345` before the server
starts.

### Share a temporary prototype link with ngrok

ngrok exposes the already-running local app through a temporary HTTPS URL. It does not replace
the application or database, so keep Docker, the app terminal, and the ngrok terminal running.

First configure ngrok once with an account token:

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
```

Then start Screen2Care in one terminal:

```bash
bash main.sh
```

In a second terminal, from the project directory, run:

```bash
bash ngrok.sh
```

ngrok will print a temporary `https://...ngrok...` URL to share. Stop sharing when the demo ends
or close the ngrok terminal. Use seeded demo data only; do not expose real patient information.

## 2. Daily use and updating

**Every day** (after a restart): open Docker Desktop and run:

```bash
bash main.sh
```

**After `git pull`.** Run `bash main.sh` again. It safely reapplies the current migrations,
updates dependencies from `pyproject.toml`, and restarts the app.

**Start again from an empty database.** This deletes all local data:

```bash
docker compose down -v
bash main.sh
```

**Show the app to others on the same Wi-Fi.** Start the server with
`uvicorn app.main:app --host 0.0.0.0 --port 8000`, then others can open
`http://<your-ip>:8000`. Use `ipconfig` to find your IP. Windows Firewall may ask you to allow port 8000.

**Look inside the database.** Use DBeaver, the VS Code PostgreSQL extension or `psql` with these
details: host `localhost`, port `5432`, database `screening_care_loop`, user `loop`, password
`loop_dev_password`.

## 3. Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://loop:loop_dev_password@localhost:5432/screening_care_loop` | Database connection |
| `JWT_SECRET` | `dev-only-change-me` | Key that signs login tokens. Use a long random value anywhere real |
| `SLA_CHECK_SECONDS` | `60` | How often the server checks for missed deadlines |
| `OLLAMA_URL` | `http://localhost:11434` | Local AI server |
| `OLLAMA_MODEL` | `llama3.2` | AI model name |
| `OLLAMA_TIMEOUT` | `240` | Seconds to wait for an AI answer |

`.env` is never committed. `.env.example` is the template.

## 4. Logins and what each role sees

`python -m app.seed_users` creates these logins, all with password `Dev@12345` (development only).
A user only ever sees the patients their role allows (`app/access.py`). The same rule applies to the
dashboard, the API and opening a record by its address: a patient who is not on your list gives
**403**.

| Login | Role | Sees and does |
|---|---|---|
| `admin1` | Admin (front desk) | All patients' names and IDs, **no clinical results**. Registers patients and assigns a clinician. Approves staff sign-ups |
| `clinician1` | Clinician | Only patients assigned to them (BC-HP-\*, BC-HR-\*). Clinical intake, plan, biopsy results, treatment |
| `clinician2` | Clinician | Only BC-DL-\* patients |
| `navigator1` | Navigator | Patients with an open care loop or an open imaging follow-up. Calls patients, books biopsies, refers malignant results to an oncologist, closes loops |
| `scheduling1` | Scheduling Manager | Patients waiting for a biopsy booking (S2) or a follow-up scan booking (R2) |
| `radiology1` | Radiologist | Patients whose imaging they reported, and follow-ups waiting for a scan (R3) or a result (R4). Marks biopsies and scans as done |
| `pathology1` | Pathologist | Patients with a biopsy on record. Writes the pathology report |
| `labdirector1` | Lab Director | Biopsies waiting for a pathology report (S3) |
| `tumorboard1` | Tumor Board (oncology team) | New BI-RADS 4/5 workups (heads-up when the loop opens), referrals sent to them, S4 alerts |
| `cmo1` | Chief Medical Officer | All patients, every missed deadline, overdue follow-ups, and every loop closed without treatment. Can restart closed loops |
| `patient1` … `patient15` | Patient | Only their own page (BC-HP-001 … BC-HR-015) |

The front-desk dashboard deliberately hides BI-RADS, density, lane and deadlines.

## 5. The whole patient journey

```
Front desk (Admin)          registers the patient, picks a clinician
        │
Clinician                   clinical intake: history, examination, imaging report with BI-RADS, plan
        │
Rules engine                chooses the screening lane (section 7)
        │
        ├── BI-RADS 4/5 ───────────► CARE LOOP (section 8)
        │                            S1 tell patient → S2 book biopsy → S3 pathology
        │                              ├── Benign    → clinician discusses it → loop closes
        │                              │                → check scan in 6 months (follow-up loop)
        │                              └── Malignant → navigator refers to oncologist (S4)
        │                                              → doctor discusses result → treatment (S5)
        │
        ├── BI-RADS 0 / 3, annual, dense, high risk ─► IMAGING FOLLOW-UP LOOP (section 9)
        │                            R1 reminder → R2 book scan → R3 scan done → R4 result
        │                              ├── BI-RADS 4/5 → care loop
        │                              └── other       → next follow-up is scheduled
        │
        └── under 40 / 75+ with short life expectancy / no imaging yet → no loop (lane only)
```

Any open loop can be **closed with a reason** (section 10). The CMO keeps the record and can restart it.

## 6. Registration and clinical intake

The intake is split so that each person only enters what is theirs to decide.

### 6.1 Registration (Admin, `/register`)

- Fields: full name, date of birth (age is calculated), phone, national ID (CNIC), Patient ID, and
  **the clinician** who will see the patient.
- **Patient ID is required** when registering a patient and must use the displayed format.
- **Returning patient:** use **Find existing patient** first. That loads the record so it can be
  updated. Typing an existing Patient ID or CNIC on a new registration is refused (409), so another
  patient's record is never overwritten by mistake.
- The date of birth cannot be today or in the future.
- Saving adds the patient to the chosen clinician's care team (`care_team_assignment`). The
  patient then appears on that clinician's dashboard under **"Registered, waiting for your clinical intake"**.
- The front desk never sees clinical data, not even in the lookup.

### 6.2 Clinical intake (Clinician, `/intake`)

- Start it from the dashboard card with **Start intake**. That opens `/intake?patient=<ID>`.
- Demographics come from registration and are read-only. The clinician cannot change them; the API
  refuses demographic fields (422).
- The form is the screen2care breast-screening proforma in 8 sections:
  1. Patient and evaluation date
  2. Chief complaint (asymptomatic or symptomatic: lump, nipple discharge, pain)
  3. Obstetric and gynaecological history (marital status, menarche, menopause, parity, OCP, HRT at age 45–55, breastfeeding)
  4. Personal medical history (breast procedures, medical history, height and weight with BMI, chest radiation, genetic test, geriatric assessment at 75+)
  5. Family history of cancer
  6. Clinical breast examination for each breast (inspection, palpation, axillary nodes). "Not answered" is stored as unknown, never as normal
  7. **Imaging: every scan with date, modality, density (mammogram/DBT only) and BI-RADS.** The clinician enters the radiology report here
  8. Plan (one or more of 8 options) and notes
- The form is signed by the **logged-in clinician**. No name is typed, and the encounter is stored
  under that clinician.
- Validation runs in the browser and again on the server (`app/schemas.py`). For example, the age
  at menarche must be 6–25 and the height is in **centimetres** (100–230).
- A double click on Save does not create two visits (idempotency key).
- **On save:** the visit, examination, scans, plan items with due dates and an unchangeable copy of
  the form (`encounter_snapshot`) are stored. A **risk tier** is calculated (below), and then
  **the rules engine runs at once**. If the result is BI-RADS 4/5, the care loop opens and the S1
  clock starts immediately.

### 6.3 Risk tier shown after saving (`app/risk_engine.py`)

| Tier | When |
|---|---|
| High | Positive BRCA1/2, TP53, PTEN or PALB2 test; chest radiation between age 10 and 30; ADH, ALH or LCIS on a biopsy; mother or sister with breast cancer before 50; a relative with a BRCA1/2 mutation |
| Medium | Dense breast (C or D) on the latest mammogram/DBT, or BI-RADS 3 |
| Low | None of the above with a Mammogram/DBT baseline (the lifetime risk percentage is not calculated) |
| Baseline assessment | No Mammogram/DBT baseline yet; continue symptom-based or clinician-directed care |

## 7. The rules engine (screening lanes)

`app/rules.py` implements the screening flowchart. `app/rules_runner.py` loads the patient's data,
applies the rules and stores the lane in `lane_assignment`, keeping the history. It runs after every
clinical intake, after every follow-up result, and with `python -m app.care_loop` for seeded patients.

1. **A suspicious result wins at any age:** BI-RADS 4 or 5 → `UrgentWorkup` (opens the care loop).
2. **Step 1, high risk (any age):**
   - Positive gene test, or chest radiation between age 10 and 30: screening starts at 25, or 8 years
     after the radiation, never before 25. Before that age → `HighRisk-Waiting`. Age 25–29 →
     `HighRisk-MRIOnly` (annual MRI). Age 30+ → `HighRisk-DBT+MRI` (alternating every 6 months).
   - Lifetime risk ≥ 20 % or ADH/ALH/LCIS: from age 30 → `HighRisk-DBT+ConsiderMRI`; earlier → `HighRisk-Waiting`.
3. **Step 2, age (average risk):** under 40 → `WellnessHold` (no routine screening unless symptomatic).
   75 and over → Step 4.
4. **Step 3, BI-RADS for ages 40–74:**

   | BI-RADS | Lane | Next imaging |
   |---|---|---|
   | 0 | `RecallBirads0` | in 30 days |
   | 1–2, density A/B | `RoutineScreening` | in 12 months |
   | 1–2, density C/D | `DenseSupplemental` | in 12 months, discuss extra imaging |
   | 3 | `ShortInterval6M` | in 6 months |
   | 4–5 | `UrgentWorkup` | care loop |
   | 6 | `Treatment` | known cancer |

   A high-risk lane still takes BI-RADS 0, 3 and 6 into account.
5. **Step 4, age 75+:** a serious illness (end-stage organ failure, advanced dementia or a severe
   comorbidity) → `SymptomaticCareOnly`. Life expectancy over 10 years → `RoutineScreening`. Under
   10 years → `SymptomaticCareOnly`. Not recorded → `DataPending`.

## 8. Care loop for BI-RADS 4/5 (S1–S5)

Page: `/loop/<patient_id>`. One loop per suspicious result (`care_episode`). The loop opens
automatically. It never opens twice for the same result: reopening is a deliberate step (section 10).

When the loop opens:

- the patient's result SMS is recorded (it is not actually sent; see section 23),
- the **S1** clock starts at the moment the result was released,
- the oncology team (`tumorboard1`) gets a heads-up on their dashboard.

| Step | Clock starts | Done when | Target | Who does it | Missed → alert to |
|---|---|---|---|---|---|
| **S1** Tell the patient | result released | patient confirms | 24 hours | Patient presses **"I received the message"** on their page, or the Navigator/Clinician logs a call as **Reached** | Navigator |
| **S2** Book the biopsy | patient confirmed | biopsy booked | 7 days | Navigator or Scheduling Manager: **date and time only** | Scheduling Manager |
| **S3** Pathology report | biopsy marked done | report saved | 5 days | Radiologist marks the biopsy done; Pathologist writes the report | Lab Director |
| **S4** Oncology referral | malignant report | referral sent | 5 days | **Navigator** | Tumor Board |
| **S5** Treatment | malignant report | treatment started | 21 days | Clinician (only after the result has been discussed) | CMO (red flag) |

**S1 contact log:** channel (phone, SMS, in person, email, letter) and outcome (reached, no answer,
wrong number, declined). **Draft call script** asks the local AI for a script that never mentions
the result. Booking the biopsy also counts as having reached the patient.

**After the pathology report:**

- **Benign** stays with the **clinician**. It appears on the clinician's dashboard with a green
  *Benign* label. The navigator does not see it and cannot book its appointment. When the clinician
  presses **"I have discussed the result with the patient"**, the loop closes (`Closed-Benign`), the
  remaining clocks stop, and a **check scan in 6 months** is scheduled in the imaging follow-up loop.
- **Malignant** goes to the **navigator**. The dashboard card **"Malignant results: refer to an
  oncologist"** shows the patient, histology and the S4 time left. On the loop page the navigator
  sees the pathology report (diagnosis, histology, ER/PR/HER2 when recorded, who reported it and
  when) and chooses the **specialty** (surgical, medical or radiation oncology), the **oncologist**
  (oncology-team staff only) and an optional note. Only the navigator can send the referral.
- **High-risk lesion or non-diagnostic** stays with the clinician. The loop stays open for their decision.

**Telling the patient the result:** the patient's page says "Your report is ready" but never shows
the result before a doctor has discussed it. A results appointment is booked (Clinician; for a
malignant result also the Navigator) with a chosen clinician. The clinician then presses **"I have
discussed the result with the patient"** (in person or by phone). Only then does the result appear on
the patient's page. Treatment cannot be recorded before this step (409).

**Treatment** (Clinician): surgery, neoadjuvant chemotherapy, chemotherapy, radiation, endocrine or
other. Recording it closes the loop (`Closed-TreatmentStarted`), stops the remaining clocks and
clears the alerts.

## 9. Imaging follow-up loop (R1–R4)

Page: `/followup/<patient_id>` (`app/followup.py`). This is a separate loop for patients whose next
step is **another scan**, not a biopsy.

| Lane | Scan | Reminder goes out | Grace after due date |
|---|---|---|---|
| `RecallBirads0` | Recall imaging (diagnostic mammogram / ultrasound) | at once (due in 30 days) | 7 days |
| `ShortInterval6M` | 6-month scan after BI-RADS 3 | 30 days before | 14 days |
| `RoutineScreening` | Annual mammogram / DBT | 30 days before | 30 days |
| `DenseSupplemental` | Annual mammogram with ultrasound / MRI | 30 days before | 30 days |
| `HighRisk-MRIOnly` | Annual MRI | 30 days before | 30 days |
| `HighRisk-DBT+MRI` | DBT / MRI alternating every 6 months | 30 days before | 30 days |
| `HighRisk-DBT+ConsiderMRI` | Annual DBT, consider MRI | 30 days before | 30 days |
| `PostBenignBiopsy` | Check scan 6 months after a benign biopsy | 30 days before | 14 days |

**How it runs:**

1. The rules engine sets one of these lanes, and a follow-up is created with status **Scheduled** and
   the due date. Nothing is shown to the navigator yet. The dashboard only says
   "N more scheduled, reminder not sent yet".
2. On the reminder date (checked every minute), the loop becomes **Open**, a reminder SMS is recorded,
   and the steps start:

| Step | Done when | Deadline | Who | Missed → alert to |
|---|---|---|---|---|
| **R1** Reminder confirmed | patient presses **"Yes, I will come for this scan"**, or a contact is logged as Reached | 14 days, never later than the due date | Patient, Navigator, Clinician | Navigator |
| **R2** Scan booked | scan type and time booked (booking also confirms R1) | the due date | Navigator, Scheduling Manager | Scheduling Manager |
| **R3** Scan done | **Mark scan as done** | due date (or booked date) + grace | Radiologist, Navigator | Navigator |
| **R4** Result recorded | BI-RADS (and density for mammogram/DBT) saved | 3 days after the scan | Clinician, Radiologist | Clinician |

3. Saving the R4 result runs the rules engine again:
   - **BI-RADS 4/5:** the follow-up closes as `Closed-Escalated`, the **care loop opens**, and the
     page jumps to it.
   - **Anything else:** the follow-up closes as `Closed-Completed` and the **next follow-up is
     scheduled** from the new lane.
4. A new result entered through a clinical intake also completes an open follow-up in the same way.

**To test it without waiting months**, bring a due date forward and refresh any dashboard:

```bash
docker exec screening_db psql -U loop -d screening_care_loop -c "UPDATE followup_loop SET due_date = current_date + 20 WHERE patient_id = 'BC-HR-014' AND status = 'Scheduled';"
```

## 10. Closing a loop and restarting it

A care loop or follow-up that cannot go on is **closed with a reason**. It is never deleted.

| Reason | Who may choose it |
|---|---|
| Lost to follow-up | Navigator, CMO |
| Transferred to another hospital | Navigator, CMO |
| Deceased | Navigator, CMO |
| Patient declined the biopsy / treatment | Clinician only (a doctor explains the risk first) |

- A note is required (at least 10 characters). There is **no minimum number of contact attempts**.
  The page shows how many unanswered attempts were logged, for information only.
- **On closing:** running clocks stop (`Cancelled`; finished ones keep their result), alerts are
  resolved, and the booked biopsy or scan, results appointment, referral and oncology heads-up are
  cancelled. Who closed it, when and why are stored.
- The navigator is taken back to the dashboard with a green message:
  *"<Name> (<ID>) is no longer in the care loop … removed from your list. The CMO keeps the
  record …"*. The patient disappears from the navigator's dashboard and list, and their loop page now
  gives 403.
- The **CMO** sees every closure under **"Loops closed without treatment"**: care loops and
  follow-ups, with reason, note, who closed it and the number of unanswered attempts.
- **Restart** (CMO or Clinician, a note is required): only for *lost to follow-up*, *declined* and
  *transferred*. **Deceased** cannot be restarted.
  - **Care loop:** a new loop opens from the same result, with the S1 clock from now.
  - **Follow-up:** a new follow-up opens with the scan due now, and the reminder goes out at once.
  - The patient comes back onto the navigator's list.

## 11. Deadlines, alerts and escalation

- The server checks every `SLA_CHECK_SECONDS` (60 s) and on every dashboard or loop page load.
- A clock past its due time becomes **Breached** and sends **one alert** to the role in the tables
  above. The alert appears on that role's dashboard and on the CMO's.
- **Mark seen** only records "I have seen this alert" (who and when). It does **not** stop the clock
  or close the alert. An alert closes by itself when the step is done or the loop is closed.
- A step done late shows **Confirmed late**. The lateness stays on record.
- Timeline colours: Running (blue, time left), Breached (red, time overdue), Confirmed (green),
  Confirmed late (amber), Cancelled and Not started (grey).

## 12. Dashboards

Each role's dashboard shows only the cards that concern it:

| Card | Who sees it |
|---|---|
| SLA alerts for you / SLA breaches across the hospital | Every clinical role / CMO |
| Registered, waiting for your clinical intake | Clinician |
| Imaging follow-up (BI-RADS 0/3, annual, high risk) / Overdue imaging follow-ups | Navigator (R1–R3), Scheduling Manager (R2), Radiologist (R3–R4), Clinician (R4) / CMO |
| Malignant results: refer to an oncologist | Navigator |
| Biopsy results to go through with the patient | Clinician (all results), Navigator (malignant only) |
| New urgent workups (BI-RADS 4/5) | Tumor Board |
| Loops closed without treatment | CMO |
| Account requests, data-quality flags | Admin |

The **patient table** shows BI-RADS, density, result date, lane, the next deadline (`S1 · 4 d overdue`,
`R2 · 3 d left` or `Scan due 07 Nov 2027`), flags, and buttons for **Plan** (Clinician),
**Follow-up** and **Care loop**.

## 13. Patient portal

Patients log in (`patient1` … or after sign-up) and see only their own page:

- **Action needed** cards: confirm they received the result message (S1), or confirm they will come
  for a scan (R1).
- **Your current status** in plain words. Before a biopsy it comes from the note the clinician
  released. After a biopsy is booked it follows the loop: biopsy booked → biopsy done → report ready
  → results discussed → specialist and treatment.
- **Your progress** steps, **Appointments** (coming up and past), **Your next scan** (follow-up due
  date or booked time), and **Notes from your care team** (only notes a clinician released).
- **The diagnosis is never shown before a doctor has discussed it.** After a closure without
  treatment, the page goes back to the released plan.

## 14. Clinical plan page and patient notes

`/plan/<patient_id>` (Clinician):

- The engine's suggested disposition (routine rescreen, short-term follow-up, urgent biopsy
  referral, high-risk surveillance) is shown. The clinician confirms it or chooses another. **A
  reason is required to override.** The overriding lane is stored as `assigned_by = Clinician`.
- The clinical note is versioned (every save is a new version).
- **Patient-friendly note:** the local AI can draft it from the clinical note. The clinician edits
  it and presses **Release to patient**. Only released notes appear on the patient's page.

## 15. Sign-up and accounts

- `/signup`, **patients:** Patient ID + date of birth + national ID. If all three match the hospital
  record, the account is active at once. There is one account per patient.
- `/signup`, **staff:** the request waits on **Account requests** (Admin menu). Approving creates the
  staff record and the login. A new clinician sees no patients until patients are assigned to them
  at registration.
- Passwords are stored with bcrypt. A login lasts 8 hours (JWT in the `access_token` cookie).

## 16. Local AI

Install [Ollama](https://ollama.com), then run `ollama pull llama3.2`. Nothing else is needed. If
Ollama is not running, the rest of the app works and the AI buttons say so.

| Feature | Where | Who |
|---|---|---|
| Patient-friendly note drafted from the clinical note, edited, then released | Clinical plan page | Clinician |
| Call script for an unanswered result (never mentions the result) | Care loop page, S1 | Navigator, Clinician |
| **Care Assistant**: answers "which of my patients are overdue?", "what alerts do I have?", "status of BC-HP-001?" with read-only tools limited to the user's own patient list | Sidebar → Care Assistant | Clinical staff |

Every AI draft is logged in `event_log` (`AIDraftCreated`). On a CPU-only laptop a draft takes
about 15–30 s. A larger model is more accurate but slower, for example
`ollama pull qwen2.5:7b` with `OLLAMA_MODEL=qwen2.5:7b`.

## 17. Data-quality flags

The number in the **Flags** column counts problems in that patient's record. It is not a measure of
medical risk and not a step number. Flags come from the view `vw_data_quality_flags`:

| Flag | Meaning | Fix |
|---|---|---|
| `RiskDataPending` | Genetic test "Never tested": risk data incomplete (counted once per patient) | Record the genetic status |
| `AbnormalCBE_RecordedAsAsymptomatic` | Abnormal breast examination on a visit marked asymptomatic (counted per visit) | Check whether the patient was symptomatic |
| `FamilyHistoryRelationUnspecified` | A relative recorded without the relation (counted per relative) | Record the relation |

## 18. Database

PostgreSQL 16 (image `pgvector/pgvector:pg16`, container `screening_db`). The files in `db/` run in
number order on an empty database.

| File | What it adds |
|---|---|
| `01_schema.sql` | Core tables, indexes and views |
| `02_seed.sql` | Staff, SLA rules and 15 test patients |
| `03_intake_form.sql` | Extra intake-form columns |
| `04_plan.sql` | New engine lanes and the high-risk surveillance plan option |
| `05_users.sql` | Logins (`app_user`) |
| `06_access.sql` | Care-team assignments, a second clinician, released test notes |
| `07_sla.sql` | SLA alerts, escalation-role logins, S2 clock fix |
| `08_signup.sql` | Staff sign-up requests, one login per patient |
| `09_oncology_notice.sql` | Heads-up to the oncology team when a BI-RADS 4/5 loop opens |
| `10_results_disclosure.sql` | Results appointment; result shown to the patient only after the doctor discusses it |
| `11_intake_v2.sql` | Intake v2: new fields, form snapshots, risk tier, plan due dates |
| `12_loop_closure.sql` | Closing a loop with a reason; letter as a contact channel |
| `13_followup_loop.sql` | Imaging follow-up loop tables; existing patients get a scheduled follow-up |
| `14_biopsy_booking.sql` | Biopsy booking is date and time only; who booked it |
| `15_oncology_referral.sql` | Two oncologists; who made the referral and the note |

**Main tables:**

| Area | Tables |
|---|---|
| People and access | `staff`, `app_user`, `signup_request`, `care_team_assignment` |
| Patient record | `patient`, `patient_risk_profile`, `family_history`, `prior_breast_procedure`, `comorbidity` |
| Visits | `encounter`, `clinical_breast_exam`, `geriatric_assessment`, `imaging_result`, `encounter_snapshot` (cannot be changed), `risk_assessment`, `plan_items`, `clinical_note` |
| Rules engine | `lane_assignment` (current lane plus history) |
| Care loop | `care_episode`, `patient_contact`, `biopsy`, `pathology_result`, `results_appointment`, `referral`, `treatment`, `team_notification` |
| Deadlines | `sla_definition`, `sla_task`, `sla_alert`, view `vw_sla_status` |
| Imaging follow-up | `followup_loop`, `followup_task`, `followup_alert`, `followup_contact`, `followup_appointment` |
| Audit | `event_log`: every important action, who did it and when |
| Views | `vw_data_quality_flags`, `vw_patient_released_notes` |

## 19. Code layout

```
app/main.py            all routes (pages and API)
app/auth.py            login, bcrypt passwords, JWT cookie, role checks
app/access.py          which patients each role may see; the dashboard patient list
app/registration.py    front-desk registration and the clinician's "waiting for intake" list
app/schemas.py         clinical proforma validation (Pydantic)
app/intake.py          saves the proforma in one transaction
app/risk_engine.py     risk tier after intake; plan → disposition
app/plan_dates.py      due dates for the chosen plan options
app/rules.py           screening rules (flowchart steps 1–4)
app/rules_runner.py    runs the rules for a patient, stores the lane, opens or updates the loops
app/care_loop.py       BI-RADS 4/5 loop: steps, clocks, closing/reopening, breach checker, dashboards
app/followup.py        imaging follow-up loop: scheduling, reminders, steps, closing/restarting
app/plan.py            clinical plan page and patient-note release
app/patient_portal.py  the patient's own page (status, progress, appointments)
app/accounts.py        patient and staff sign-up, admin approval
app/llm.py             local AI: note drafts, call scripts, Care Assistant
app/seed_users.py      development logins
app/database.py        database connection (reads .env)
pyproject.toml         project metadata and Python dependencies
Dockerfile             container image for the application
main.sh                one-command local setup and startup
app/templates/         HTML pages (Jinja2); base.html = layout and sidebar per role
app/static/            app.css (design system, light and dark), intake.css and intake.js (forms)
db/                    SQL files (section 18)
tests/                 pytest suite (section 21)
```

## 20. API reference

All endpoints need a login (cookie, or `Authorization: Bearer <token>`) except login, sign-up and
health. The full interactive list is at `/docs`. A role that may not do a step gets 403. A step in
the wrong order gets 409, for example booking treatment before the result was discussed.

| Method and path | Who | What it does |
|---|---|---|
| `POST /api/login`, `POST /api/logout` | anyone | log in or out |
| `POST /api/registration` | Admin | register or update a patient and assign a clinician |
| `GET /api/registration/patients/{id}` | Admin | demographics and assigned clinicians |
| `POST /api/intake` | Clinician | save the clinical proforma and run the engine |
| `GET /api/intake/patients/{id}` | Clinician | patient and earlier intakes |
| `GET /api/patients`, `GET /api/patients/{id}` | staff | patient list / one record (role-limited) |
| `POST /api/patients/{id}/run-engine` | Clinician, Admin | run the rules engine |
| `POST /api/patients/{id}/plan` | Clinician | save the clinical plan |
| `POST /api/patients/{id}/contact` | Navigator, Clinician | S1 contact attempt |
| `POST /api/patients/{id}/biopsy` | Navigator, Scheduling Manager | book the biopsy (`scheduled_for`) |
| `POST /api/patients/{id}/biopsy/performed` | Radiologist | biopsy done (starts S3) |
| `POST /api/patients/{id}/pathology` | Pathologist | pathology report |
| `POST /api/patients/{id}/referral/assign` | Navigator | refer a malignant result to an oncologist |
| `POST /api/patients/{id}/results-appointment` | Clinician (Navigator: malignant only) | book the results appointment |
| `POST /api/patients/{id}/result-disclosed` | Clinician | the result has been discussed with the patient |
| `POST /api/patients/{id}/treatment` | Clinician | treatment started (closes the loop) |
| `POST /api/patients/{id}/close-loop`, `/reopen-loop` | see section 10 | close or restart the care loop |
| `POST /api/patients/{id}/followup/contact`, `/book`, `/performed`, `/report`, `/close`, `/reopen` | see section 9 | imaging follow-up steps |
| `POST /api/me/acknowledge`, `POST /api/me/followup-confirm` | Patient | confirm the result message / the scan |
| `GET /api/alerts`, `POST /api/alerts/{id}/seen` | staff | SLA alerts |
| `GET /api/notifications`, `POST /api/notifications/{id}/seen` | Tumor Board | BI-RADS 4/5 heads-up |
| `POST /api/sla/check` | Admin, CMO | run the breach check now |
| `GET /api/data-quality-flags` | staff | data-quality flags |
| `POST /api/signup/patient`, `/api/signup/staff` | anyone | sign-up |
| `POST /api/admin/signup-requests/{id}/{approve or reject}` | Admin | decide a staff request |
| `POST /api/assistant`, `/api/patients/{id}/draft-note`, `/release-note`, `/call-script`, `GET /api/ai/status` | clinical staff | local AI |

## 21. Tests

```bash
python -m pytest -q
```

The tests need the database running. They create their own test patients (`TEST-…`, `BC-TS-901`)
and delete them afterwards. They cover:

| File | Covers |
|---|---|
| `test_rules.py` | flowchart rules, 75+ life expectancy, intake → engine |
| `test_intake.py` | proforma validation, risk tiers, plan dates, registration/intake split, permissions |
| `test_access.py`, `test_auth.py` | who sees which patient, logins and roles |
| `test_sla.py` | the full S1–S5 loop with every escalation |
| `test_results.py` | patient journey and result disclosure |
| `test_biopsy_booking.py` | biopsy booking by date and time |
| `test_pathology_routing.py` | benign → clinician and closure; malignant → navigator referral |
| `test_closure.py` | closing, CMO review and restarting the care loop |
| `test_followup.py` | the R1–R4 follow-up loop, escalation to the care loop, closing and restarting |
| `test_signup_ai.py` | sign-up and AI endpoints |

## 22. Troubleshooting

| Problem | Cause and fix |
|---|---|
| Login fails for everyone | Wrong password: it is `Dev@12345` (capital D). Or `bash main.sh` was not run or failed. Run it again and look for `Done.` |
| `relation "app_user" does not exist` | An old database volume from an earlier branch, so the SQL files never ran. Run `docker compose down -v`, `docker compose up -d`, then `seed_users` |
| `password authentication failed for user "loop"` | Another PostgreSQL installed on Windows is using port 5432. Stop that service or change the port |
| `failed to connect to the docker API` / connection refused on 5432 | Docker Desktop is not running. Start it, then `docker start screening_db` |
| "This patient is not on your list" (403) | The patient is not in your role's scope (section 4). For example, BC-DL patients belong to `clinician2` |
| A follow-up does not appear for the navigator | It is still **Scheduled**; the reminder date has not come (section 9) |
| Intake will not save | Read the red message. Common causes: height in feet instead of centimetres, menarche over 25, a scan date after the evaluation date |
| AI buttons say offline | Ollama is not running, or the model is not pulled |

## 23. Known limitations

- **SMS and phone calls are not really sent.** They are only recorded in `patient_contact` /
  `followup_contact`.
- **Only the first escalation level is used.** `sla_definition` also holds a second level
  (for example S2 → RadiologyHead after 240 h), but the checker does not send it yet.
- **The clinical intake form currently has no fields for "Life expectancy over 10 years" and
  "High-risk biopsy finding (ADH/ALH/LCIS)"** (form layout from commit `9b4899c`). The API still
  accepts both. Through the form, every patient aged 75+ gets `DataPending`, and a previous
  ADH/ALH/LCIS does not put the patient on the high-risk pathway.
- **Under 40 with average risk**, BI-RADS 0 or 3 does not create a follow-up (lane `WellnessHold`, flowchart Step 2).
- The intake form can only be started from the clinician's dashboard (**Start intake**); the
  "Find patient by ID" button is hidden in the current layout.
- The two oncologists added by `db/15` and the RadiologyHead role have no logins.
- Development settings only: the shared password `Dev@12345`, the default `JWT_SECRET` and the
  database password must all be changed, and HTTPS added, before any real patient data is used.
