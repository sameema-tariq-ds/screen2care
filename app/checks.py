"""Clinical warnings shared by preview and persisted assessment paths."""

from app.schemas import ExamStatus, IntakeForm, PlanOption, YesNoUnknown


def collect_warnings(form: IntakeForm) -> list[str]:
    warnings: list[str] = []
    exams = (form.cbe_right, form.cbe_left)
    if form.presentation is False and any(
        exam.inspection == ExamStatus.ABNORMAL
        or exam.mass == ExamStatus.ABNORMAL
        or exam.axillary_nodes == ExamStatus.ABNORMAL
        for exam in exams
    ):
        warnings.append("Abnormal clinical examination recorded for an asymptomatic presentation.")
    if any(scan.birads in {4, 5, 6} for scan in form.imaging) and PlanOption.URGENT_BIOPSY not in form.plan:
        warnings.append("BI-RADS 4-6 normally requires urgent biopsy referral.")
    if any(scan.birads == 3 for scan in form.imaging) and PlanOption.ROUTINE_RESCREEN in form.plan:
        warnings.append("BI-RADS 3 generally needs short-term follow-up.")
    if any(scan.density in {"C", "D"} for scan in form.imaging) and PlanOption.ROUTINE_RESCREEN in form.plan:
        warnings.append("Dense breast tissue may require supplemental imaging review.")
    return warnings

