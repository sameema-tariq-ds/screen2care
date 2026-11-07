import json
from datetime import datetime, time

from sqlalchemy import text

from app.assess import assess
from app.database import engine
from app.handover import make_handover
from app.plan_dates import due_dates
from app.schemas import ExamStatus, IntakeForm, PlanOption, GeneticStatus

ADMIN_STAFF_ID = 1


def _value(item):
    return item.value if hasattr(item, "value") else item


def _tri_bool(item):
    if item is None:
        return None
    return _value(item) == "Yes"


def _disposition(form: IntakeForm) -> str:
    if PlanOption.URGENT_BIOPSY in form.plan:
        return "UrgentBiopsyReferral"
    if PlanOption.SHORT_TERM_FOLLOW_UP in form.plan:
        return "ShortTermFollowUp"
    return "RoutineRescreen"


def _chief_complaint(form: IntakeForm) -> str:
    return "Symptomatic presentation" if form.presentation else "Asymptomatic routine screening"


def _exam_params(exam):
    return {
        "inspection_status": _value(exam.inspection),
        "inspection_normal": exam.inspection == ExamStatus.NORMAL,
        "inspection_finding": exam.inspection_finding,
        "mass_status": _value(exam.mass),
        "mass_present": exam.mass == ExamStatus.ABNORMAL,
        "mass_size_mm": exam.mass_size_mm,
        "mass_mobility": exam.mass_mobility,
        "mass_consistency": exam.mass_consistency,
        "axillary_node_status": _value(exam.axillary_nodes),
        "axillary_node_palpable": exam.axillary_nodes == ExamStatus.ABNORMAL,
    }


def save_intake(form: IntakeForm) -> dict:
    """Persist an intake atomically and record the submitted payload in the audit log."""
    assessment = assess(form)
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT patient_id, encounter_id FROM encounter WHERE idempotency_key = :key"),
            {"key": form.idempotency_key},
        ).mappings().first()
        if existing:
            return {
                "patient_id": existing["patient_id"],
                "encounter_id": existing["encounter_id"],
                "duplicate": True,
                "age": form.age,
                "bmi": form.bmi,
                "assessment": assessment.as_dict(),
                "warnings": form.warnings(),
            }
        patient_id = conn.execute(
            text("SELECT patient_id FROM patient WHERE national_id = :nid"), {"nid": form.national_id}
        ).scalar()
        returning = patient_id is not None
        if not patient_id:
            patient_id = conn.execute(
                text("SELECT 'BC-' || to_char(nextval('patient_number_seq'), 'FM00000')")
            ).scalar()
            conn.execute(text("""
                INSERT INTO patient (patient_id, full_name, date_of_birth, national_id, phone, created_by)
                VALUES (:pid, :name, :dob, :nid, :phone, :by)
            """), {"pid": patient_id, "name": form.full_name, "dob": form.date_of_birth,
                   "nid": form.national_id, "phone": form.phone, "by": ADMIN_STAFF_ID})
        else:
            conn.execute(text("""
                UPDATE patient SET full_name=:name, date_of_birth=:dob, phone=:phone
                WHERE patient_id=:pid
            """), {"pid": patient_id, "name": form.full_name, "dob": form.date_of_birth, "phone": form.phone})

        gene = _value(form.genetic_gene) if form.genetic_gene else None
        if form.genetic_gene_other:
            gene = form.genetic_gene_other
        genetic_status = _value(form.genetic_status)
        conn.execute(text("""
            INSERT INTO patient_risk_profile
              (patient_id, race_ethnicity, carrier_relative_status, menarche_age, menopausal_status, menopause_age, parity,
               age_first_birth, ocp_use, hrt_use, hrt_duration_years, height_cm, weight_kg,
               genetic_status, genetic_mutation, chest_radiation_status, chest_radiation_age,
               chest_radiation_years, high_risk_biopsy, lifetime_risk_tool,
               prior_biopsy_count, prior_biopsy_atypia,
               personal_breast_cancer, personal_breast_cancer_status, personal_mastectomy, personal_mastectomy_status,
               pregnancy_history, pregnancy_history_status, breastfeeding_history, breastfeeding_history_status,
               mri_pacemaker, mri_pacemaker_status, mri_implants, mri_implants_status, mri_kidney_problems,
               mri_kidney_problems_status, risk_data_status)
            VALUES (:pid,:race,:carrier,:menarche,:menopause,:menopause_age,:parity,:first_birth,:ocp,:hrt,:hrt_years,
                    :height,:weight,:genetic,:gene,:radiation,:radiation_age,:radiation_years,:lesion,
                    :risk_tool,:biopsy_count,:biopsy_atypia,:personal_cancer,
                    :personal_cancer_status,:mastectomy,:mastectomy_status,:pregnancy,:pregnancy_status,
                    :breastfeeding,:breastfeeding_status,:pacemaker,:pacemaker_status,:implants,:implants_status,
                    :kidney,:kidney_status,:data_status)
            ON CONFLICT (patient_id) DO UPDATE SET
              race_ethnicity=EXCLUDED.race_ethnicity,
              carrier_relative_status=EXCLUDED.carrier_relative_status, menarche_age=EXCLUDED.menarche_age,
              menopausal_status=EXCLUDED.menopausal_status, menopause_age=EXCLUDED.menopause_age,
              parity=EXCLUDED.parity, age_first_birth=EXCLUDED.age_first_birth, ocp_use=EXCLUDED.ocp_use,
              hrt_use=EXCLUDED.hrt_use, hrt_duration_years=EXCLUDED.hrt_duration_years,
              height_cm=EXCLUDED.height_cm, weight_kg=EXCLUDED.weight_kg, genetic_status=EXCLUDED.genetic_status,
              genetic_mutation=EXCLUDED.genetic_mutation, chest_radiation_status=EXCLUDED.chest_radiation_status,
              chest_radiation_age=EXCLUDED.chest_radiation_age, chest_radiation_years=EXCLUDED.chest_radiation_years,
              high_risk_biopsy=EXCLUDED.high_risk_biopsy,
              lifetime_risk_tool=EXCLUDED.lifetime_risk_tool, prior_biopsy_count=EXCLUDED.prior_biopsy_count,
              prior_biopsy_atypia=EXCLUDED.prior_biopsy_atypia, personal_breast_cancer=EXCLUDED.personal_breast_cancer,
              personal_breast_cancer_status=EXCLUDED.personal_breast_cancer_status,
              personal_mastectomy=EXCLUDED.personal_mastectomy, personal_mastectomy_status=EXCLUDED.personal_mastectomy_status,
              pregnancy_history=EXCLUDED.pregnancy_history, pregnancy_history_status=EXCLUDED.pregnancy_history_status,
              breastfeeding_history=EXCLUDED.breastfeeding_history, breastfeeding_history_status=EXCLUDED.breastfeeding_history_status,
              mri_pacemaker=EXCLUDED.mri_pacemaker, mri_pacemaker_status=EXCLUDED.mri_pacemaker_status,
              mri_implants=EXCLUDED.mri_implants, mri_implants_status=EXCLUDED.mri_implants_status,
              mri_kidney_problems=EXCLUDED.mri_kidney_problems, mri_kidney_problems_status=EXCLUDED.mri_kidney_problems_status,
              risk_data_status=EXCLUDED.risk_data_status, updated_at=now()
        """), {
            "pid": patient_id, "race": form.race_ethnicity,
            "carrier": _value(form.carrier_relative_status), "menarche": form.menarche_age,
            "menopause": form.menopausal_status, "menopause_age": form.menopause_age, "parity": form.parity,
            "first_birth": form.age_first_birth, "ocp": form.ocp_use, "hrt": _tri_bool(form.hrt_use),
            "hrt_years": form.hrt_duration_years, "height": form.height_cm, "weight": form.weight_kg,
            "genetic": genetic_status, "gene": gene, "radiation": _value(form.chest_radiation),
            "radiation_age": form.chest_radiation_age, "radiation_years": form.chest_radiation_years,
            "lesion": _value(form.high_risk_biopsy), "risk_tool": _value(form.lifetime_risk_tool) if form.lifetime_risk_tool else None,
            "biopsy_count": form.prior_biopsy_count,
            "biopsy_atypia": _value(form.prior_biopsy_atypia), "personal_cancer": _tri_bool(form.personal_breast_cancer),
            "personal_cancer_status": _value(form.personal_breast_cancer), "mastectomy": _tri_bool(form.personal_mastectomy),
            "mastectomy_status": _value(form.personal_mastectomy), "pregnancy": _tri_bool(form.pregnancy_history),
            "pregnancy_status": _value(form.pregnancy_history), "breastfeeding": _tri_bool(form.breastfeeding_history),
            "breastfeeding_status": _value(form.breastfeeding_history), "pacemaker": _tri_bool(form.mri_pacemaker),
            "pacemaker_status": _value(form.mri_pacemaker), "implants": _tri_bool(form.mri_implants),
            "implants_status": _value(form.mri_implants), "kidney": _tri_bool(form.mri_kidney_problems),
            "kidney_status": _value(form.mri_kidney_problems),
            "data_status": "Pending",
        })

        for relative in form.family_history:
            conn.execute(text("""
                INSERT INTO family_history
                  (patient_id, family_side, relation, relation_degree, cancer_type, age_at_diagnosis)
                VALUES (:pid,:side,:relation,:degree,:cancer,:age)
            """), {"pid": patient_id, "side": _value(relative.family_side), "relation": relative.relation,
                   "degree": 1 if relative.relation.lower() in {"mother", "father", "sister", "brother", "daughter", "son"} else 2,
                   "cancer": _value(relative.cancer_type), "age": relative.age_at_diagnosis})

        for procedure in form.prior_breast_history:
            conn.execute(text("""
                INSERT INTO prior_breast_procedure (patient_id, procedure_type, result_summary)
                VALUES (:pid,:procedure,:details)
            """), {"pid": patient_id, "procedure": procedure[:20], "details": form.prior_breast_details})

        disposition = _disposition(form)
        encounter_id = conn.execute(text("""
            INSERT INTO encounter
              (patient_id, encounter_date, encounter_type, is_symptomatic, chief_complaint, entered_by, idempotency_key,
               lump_side, lump_duration, nipple_discharge_side, nipple_discharge_color, skin_changes,
               pain_type, pain_severity, disposition, followup_months, plan_options, warning_override_reason, examiner_name, signed_date,
               notified_person, notified_at, patient_reached, biopsy_followup_result, biopsy_followup_date)
            VALUES (:pid,:date,:type,:symptomatic,:complaint,:by,:idempotency_key,:lump,:lump_duration,:discharge_side,
                    :discharge_color,:skin,:pain,:severity,:disposition,:followup,:plan,:override,:examiner,:signed,
                    :notified,:notified_at,:reached,:biopsy_result,:biopsy_date)
            RETURNING encounter_id
        """), {"pid": patient_id, "date": form.evaluation_date, "type": "Diagnostic" if form.presentation else "Screening",
               "symptomatic": form.presentation, "complaint": _chief_complaint(form), "by": ADMIN_STAFF_ID,
               "idempotency_key": form.idempotency_key,
               "lump": _value(form.lump_side) if form.lump_side else None, "lump_duration": form.lump_duration,
               "discharge_side": _value(form.nipple_discharge_side) if form.nipple_discharge_side else None,
               "discharge_color": form.nipple_discharge_color, "skin": form.skin_changes or None,
               "pain": form.pain_type, "severity": form.pain_severity, "disposition": disposition,
               "followup": form.followup_months, "plan": [_value(item) for item in form.plan], "override": form.warning_override_reason,
               "examiner": form.examiner_name, "signed": form.signed_date, "notified": form.notified_person,
               "notified_at": form.notified_at, "reached": form.patient_reached,
               "biopsy_result": form.biopsy_follow_up.result if form.biopsy_follow_up else None,
               "biopsy_date": form.biopsy_follow_up.date if form.biopsy_follow_up else None,
               }).scalar()

        conn.execute(text("""
            INSERT INTO assessments
              (patient_id, encounter_id, tier, actionable, urgency, reasons, missing, rules_version)
            VALUES (:pid, :eid, :tier, :actionable, :urgency, CAST(:reasons AS JSONB),
                    CAST(:missing AS JSONB), :rules_version)
        """), {"pid": patient_id, "eid": encounter_id, **{
            "tier": assessment.tier, "actionable": assessment.actionable,
            "urgency": assessment.urgency, "reasons": json.dumps(assessment.reasons),
            "missing": json.dumps(assessment.missing), "rules_version": assessment.rules_version,
        }})

        for option, due_date in due_dates(form.plan, form.evaluation_date, form.followup_months).items():
            conn.execute(text("""
                INSERT INTO plan_items (patient_id, encounter_id, plan_option, due_date)
                VALUES (:pid, :eid, :option, :due_date)
            """), {"pid": patient_id, "eid": encounter_id, "option": option, "due_date": due_date})

        handover = make_handover(patient_id, encounter_id, assessment)
        conn.execute(text("""
            INSERT INTO handover (patient_id, encounter_id, tier, actionable, urgency, contract)
            VALUES (:pid, :eid, :tier, :actionable, :urgency, CAST(:contract AS JSONB))
        """), {"pid": patient_id, "eid": encounter_id, "tier": handover.tier,
               "actionable": handover.actionable, "urgency": handover.urgency,
               "contract": json.dumps({"reasons": handover.reasons, "missing": handover.missing,
                                        "rules_version": handover.rules_version})})

        for laterality, exam in (("R", form.cbe_right), ("L", form.cbe_left)):
            values = _exam_params(exam)
            conn.execute(text("""
                INSERT INTO clinical_breast_exam
                  (encounter_id,laterality,inspection_normal,inspection_finding,mass_present,mass_size_mm,
                   mass_mobility,mass_consistency,axillary_node_palpable,inspection_status,mass_status,axillary_node_status)
                VALUES (:eid,:side,:inspection_normal,:inspection_finding,:mass_present,:mass_size_mm,:mass_mobility,
                        :mass_consistency,:axillary_node_palpable,:inspection_status,:mass_status,:axillary_node_status)
            """), {"eid": encounter_id, "side": laterality, **values})

        for scan in form.imaging:
            conn.execute(text("""
                INSERT INTO imaging_result
                  (encounter_id,patient_id,modality,laterality,birads_category,density,result_released_at,
                   radiologist_name,radiologist_id,performed_date)
                VALUES (:eid,:pid,:mod,'B',:birads,:density,:released,:radiologist,:radiologist_id,:performed)
            """), {"eid": encounter_id, "pid": patient_id, "mod": _value(scan.modality), "birads": scan.birads,
                   "density": scan.density, "released": datetime.combine(scan.date, time.min),
                   "radiologist": scan.radiologist_name, "radiologist_id": None, "performed": scan.date})

        details = form.model_dump(mode="json")
        details.update({"encounter_id": encounter_id, "returning_patient": returning, "age": form.age})
        conn.execute(text("""
            INSERT INTO event_log (patient_id,event_type,actor_id,details)
            VALUES (:pid,'IntakeSubmitted',:actor,CAST(:details AS JSONB))
        """), {"pid": patient_id, "actor": ADMIN_STAFF_ID, "details": json.dumps(details)})

    return {
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "returning_patient": returning,
        "age": form.age,
        "bmi": form.bmi,
        "duplicate": False,
        "assessment": assessment.as_dict(),
        "warnings": form.warnings(),
    }
