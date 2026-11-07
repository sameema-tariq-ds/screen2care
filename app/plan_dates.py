"""Calculate plan due dates without database or web dependencies."""

from calendar import monthrange
from datetime import date, timedelta

from app.schemas import PlanOption


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def due_dates(plan: list[PlanOption], evaluation_date: date, followup_months: int | None = None) -> dict[str, date]:
    dates: dict[str, date] = {}
    if PlanOption.SHORT_TERM_FOLLOW_UP in plan:
        dates[PlanOption.SHORT_TERM_FOLLOW_UP.value] = add_months(evaluation_date, followup_months or 6)
    if PlanOption.ANNUAL_MRI in plan:
        dates[PlanOption.ANNUAL_MRI.value] = evaluation_date + timedelta(days=365)
    if PlanOption.ANNUAL_DBT_MRI_6M in plan:
        dates[PlanOption.ANNUAL_DBT_MRI_6M.value] = evaluation_date + timedelta(days=182)
    if PlanOption.ROUTINE_RESCREEN in plan:
        dates[PlanOption.ROUTINE_RESCREEN.value] = evaluation_date + timedelta(days=365)
    return dates

