from datetime import date
from enum import StrEnum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Side(StrEnum):
    RIGHT = "Right"
    LEFT = "Left"
    BOTH = "Both"


class YesNoUnknown(StrEnum):
    YES = "Yes"
    NO = "No"
    UNKNOWN = "Unknown"


class GeneticStatus(StrEnum):
    NEVER_TESTED = "Never tested"
    NEGATIVE = "Negative"
    POSITIVE = "Positive"


class GeneticGene(StrEnum):
    BRCA1 = "BRCA1"
    BRCA2 = "BRCA2"
    TP53 = "TP53"
    PTEN = "PTEN"
    PALB2 = "PALB2"
    OTHER = "Other"


class KnownGeneticMutation(StrEnum):
    BRCA1 = "BRCA1"
    BRCA2 = "BRCA2"
    NEGATIVE = "Negative"
    UNKNOWN = "Unknown"


class HighRiskBiopsy(StrEnum):
    NONE = "None"
    ADH = "ADH"
    ALH = "ALH"
    LCIS = "LCIS"
    UNKNOWN = "Unknown"


class ExamStatus(StrEnum):
    NOT_ANSWERED = "Not answered"
    NORMAL = "Normal"
    ABNORMAL = "Abnormal"


class ImagingModality(StrEnum):
    MAMMOGRAM = "Mammogram"
    DBT = "DBT"
    ULTRASOUND = "Ultrasound"
    MRI = "MRI"


class PlanOption(StrEnum):
    STANDARD_WELLNESS = "Standard Wellness & Awareness Tracking"
    ROUTINE_RESCREEN = "Routine Rescreening (Mammogram/DBT in 12–24 Months)"
    ANNUAL_MRI = "Annual Breast MRI Only"
    ANNUAL_DBT_MRI_6M = "High-Risk Staggered Screening (Annual Mammogram + Annual MRI alternating every 6 months)"
    GENETICS_REFERRAL = "Genetic Counseling & Testing Referral"
    SHORT_TERM_FOLLOW_UP = "Short-Term Diagnostic Follow-up (Repeat Imaging at strict 6-Month mark)"
    URGENT_BIOPSY = "Urgent Referral for Tissue Diagnosis (Core Needle Biopsy)"
    STOP_ROUTINE = "Stop Routine Screening (Switch to Symptomatic Care Plan only)"
    LEGACY_ANNUAL_MRI = "Annual MRI"
    LEGACY_ANNUAL_DBT_MRI_6M = "Annual DBT + MRI every 6 months"
    LEGACY_STOP_ROUTINE = "Stop routine screening"
    LEGACY_GENETICS_REFERRAL = "Genetics referral"
    LEGACY_ROUTINE_RESCREEN = "Routine rescreening"
    LEGACY_SHORT_TERM_FOLLOW_UP = "Short-term diagnostic follow-up"
    LEGACY_URGENT_BIOPSY = "Urgent biopsy referral"


class CancerType(StrEnum):
    BREAST = "Breast"
    OVARIAN = "Ovarian"
    PANCREATIC = "Pancreatic"
    PROSTATE = "Prostate"
    OTHER = "Other"


class FamilySide(StrEnum):
    MOTHER = "Mother's side"
    FATHER = "Father's side"
    UNKNOWN = "Unknown side"


class MaritalStatus(StrEnum):
    MARRIED = "Married"
    UNMARRIED = "Unmarried"


class Relative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family_side: FamilySide
    relation: str = Field(min_length=2, max_length=30)
    relation_degree: Optional[int] = Field(None, ge=1, le=2)
    cancer_type: CancerType
    age_at_diagnosis: int = Field(ge=1, le=120)
    known_genetic_mutations: KnownGeneticMutation = KnownGeneticMutation.UNKNOWN


class BreastExam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inspection: ExamStatus
    inspection_finding: Optional[str] = Field(None, max_length=100)
    nipple_discharge_color: Optional[str] = Field(None, pattern=r"^(None|Bloody|Clear|Milky)$")
    skin_change: Optional[str] = Field(None, pattern=r"^(Dimpling|Retraction|Scaling / rash)$")
    mass: ExamStatus
    mass_size_mm: Optional[int] = Field(None, ge=1, le=300)
    mass_mobility: Optional[str] = Field(None, pattern=r"^(Mobile|Fixed)$")
    mass_consistency: Optional[str] = Field(None, pattern=r"^(Soft|Firm|Hard)$")
    axillary_nodes: ExamStatus

    @model_validator(mode="after")
    def validate_details(self):
        if self.inspection == ExamStatus.ABNORMAL and not self.inspection_finding:
            raise ValueError("Describe an abnormal inspection finding.")
        if self.mass == ExamStatus.ABNORMAL and not self.mass_size_mm:
            raise ValueError("Enter the size of an abnormal mass.")
        if self.mass != ExamStatus.ABNORMAL:
            self.mass_size_mm = self.mass_mobility = self.mass_consistency = None
        if self.inspection != ExamStatus.ABNORMAL:
            self.inspection_finding = None
            self.nipple_discharge_color = None
            self.skin_change = None
        return self


class ImagingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    modality: ImagingModality
    density: Optional[str] = Field(None, pattern=r"^[ABCD]$")
    birads: int = Field(ge=0, le=6)
    radiologist_name: Optional[str] = Field(None, min_length=2, max_length=150)

    @model_validator(mode="after")
    def validate_density(self):
        if self.modality in {ImagingModality.MRI, ImagingModality.ULTRASOUND}:
            self.density = None
        return self


class BiopsyFollowUp(BaseModel):
    result: str = Field(pattern=r"^(Benign|ADH/LCIS|Cancer)$")
    date: date


class BiopsyEntry(BaseModel):
    date: date
    result: str = Field(pattern=r"^(Benign|ADH/LCIS|Cancer|Unknown)$")
    details: Optional[str] = Field(None, max_length=200)


class IntakeForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=150)
    date_of_birth: date
    patient_id: str = Field(pattern=r"^BC-[A-Z]{2}-\d{3}$", max_length=20)
    phone: str = Field(min_length=7, max_length=30)
    evaluation_date: date
    idempotency_key: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=100)
    presentation: Optional[bool] = None

    lump_side: Optional[Side] = None
    lump_duration: Optional[str] = Field(None, max_length=50)
    nipple_discharge_side: Optional[Side] = None
    nipple_discharge_color: Optional[str] = Field(None, pattern=r"^(Bloody|Clear|Milky)$")
    skin_changes: list[str] = []
    pain_type: Optional[str] = Field(None, pattern=r"^(Cyclical|Non-cyclical)$")
    pain_severity: Optional[int] = Field(None, ge=1, le=10)
    ocp_use: Optional[str] = Field(None, pattern=r"^(Current|Past|Never)$")

    marital_status: MaritalStatus
    menarche_age: Optional[int] = Field(None, ge=6, le=25)
    menopausal_status: Optional[str] = Field(None, pattern=r"^(Premenopausal|Perimenopausal|Postmenopausal)$")
    menopause_age: Optional[int] = Field(None, ge=20, le=70)
    parity: Optional[int] = Field(None, ge=0, le=20)
    age_first_birth: Optional[int] = Field(None, ge=10, le=60)
    chest_radiation: YesNoUnknown
    chest_radiation_age: Optional[int] = Field(None, ge=1, le=100)
    chest_radiation_years: Optional[int] = Field(None, ge=0, le=100)
    high_risk_biopsy: Optional[HighRiskBiopsy] = None
    genetic_status: GeneticStatus
    genetic_gene: Optional[GeneticGene] = None
    genetic_gene_other: Optional[str] = Field(None, max_length=80)
    geriatric_end_stage_failure: Optional[YesNoUnknown] = None
    geriatric_adl_independent: Optional[YesNoUnknown] = None
    hrt_use: Optional[YesNoUnknown] = None
    hrt_duration_years: Optional[float] = Field(None, ge=0, le=60)
    prior_biopsy_count: Optional[int] = Field(0, ge=0, le=100)
    prior_biopsy_atypia: Optional[YesNoUnknown] = None
    personal_breast_cancer: YesNoUnknown
    personal_mastectomy: YesNoUnknown
    pregnancy_history: YesNoUnknown
    breastfeeding_history: YesNoUnknown
    height_cm: float = Field(..., ge=100, le=230)
    weight_kg: float = Field(..., ge=25, le=300)
    # The browser marks this select required and submits an explicit value.
    # Keep the default for compatibility with older API snapshots.
    prior_breast_history: str = Field("None", pattern=r"^(None|Biopsy|Lumpectomy|Cyst Aspiration|Implants)$")
    prior_breast_details: Optional[str] = Field(None, max_length=200)
    biopsy_history: list[BiopsyEntry] = Field(default_factory=list, max_length=20)
    biopsy_not_done: bool = False
    family_history: list[Relative] = []
    family_history_none: bool
    family_history_reviewed: bool = False

    cbe_right: BreastExam
    cbe_left: BreastExam
    imaging: list[ImagingEntry] = Field(max_length=20)
    imaging_not_done: bool

    plan: list[PlanOption] = Field(min_length=1)
    clinician_notes: Optional[str] = Field(None, max_length=2000)
    warning_override_reason: Optional[str] = Field(None, max_length=400)
    followup_months: Optional[int] = Field(None, ge=1, le=24)
    examiner_name: str = Field(min_length=2, max_length=150)
    signed_date: date
    notified_person: Optional[str] = Field(None, max_length=150)
    notified_at: Optional[date] = None
    patient_reached: Optional[bool] = None
    biopsy_follow_up: Optional[BiopsyFollowUp] = None

    @property
    def age(self) -> int:
        return self.evaluation_date.year - self.date_of_birth.year - (
            (self.evaluation_date.month, self.evaluation_date.day)
            < (self.date_of_birth.month, self.date_of_birth.day)
        )

    @property
    def bmi(self) -> float | None:
        if self.height_cm is None or self.weight_kg is None:
            return None
        return round(self.weight_kg / ((self.height_cm / 100) ** 2), 1)

    def warnings(self) -> list[str]:
        warnings = []
        if self.presentation is False and any(
            exam.inspection == ExamStatus.ABNORMAL or exam.mass == ExamStatus.ABNORMAL
            or exam.axillary_nodes == ExamStatus.ABNORMAL
            for exam in (self.cbe_right, self.cbe_left)
        ):
            warnings.append("Abnormal clinical examination recorded for an asymptomatic presentation.")
        if any(scan.birads in (4, 5, 6) for scan in self.imaging) and PlanOption.URGENT_BIOPSY not in self.plan:
            warnings.append("BI-RADS 4–6 normally requires urgent biopsy referral; clinician override is recorded by the plan.")
        if any(scan.birads == 3 for scan in self.imaging) and PlanOption.ROUTINE_RESCREEN in self.plan:
            warnings.append("BI-RADS 3 generally needs short-term follow-up rather than routine rescreening.")
        if any(scan.density in ("C", "D") for scan in self.imaging) and PlanOption.ROUTINE_RESCREEN in self.plan:
            warnings.append("Dense breast tissue may require supplemental imaging review.")
        return warnings

    @model_validator(mode="after")
    def check_rules(self):
        if self.prior_breast_history == "None":
            self.prior_breast_details = None
        if self.date_of_birth >= self.evaluation_date:
            raise ValueError("Date of birth must be before evaluation date.")
        if self.presentation is None:
            raise ValueError("Select whether the patient is symptomatic or asymptomatic.")
        if self.presentation is False:
            self.lump_side = self.lump_duration = None
            self.nipple_discharge_side = self.nipple_discharge_color = None
            self.skin_changes = []
            self.pain_type = self.pain_severity = None
        if self.marital_status == MaritalStatus.UNMARRIED:
            self.parity = self.age_first_birth = None
            self.pregnancy_history = self.breastfeeding_history = YesNoUnknown.UNKNOWN
        if self.menopausal_status != "Postmenopausal":
            self.menopause_age = None
        if self.age <= 44:
            self.menopause_age = None
        if self.chest_radiation != YesNoUnknown.YES:
            self.chest_radiation_age = self.chest_radiation_years = None
        elif self.chest_radiation_age is not None and self.chest_radiation_age > self.age:
            raise ValueError("Chest-radiation age cannot be greater than the patient's current age.")
        elif self.chest_radiation_years is not None and self.chest_radiation_years > self.age:
            raise ValueError("Chest-radiation duration cannot exceed the patient's current age.")
        if self.hrt_use != YesNoUnknown.YES:
            self.hrt_duration_years = None
        if self.genetic_status != GeneticStatus.POSITIVE:
            self.genetic_gene = self.genetic_gene_other = None
        if self.age < 75:
            self.geriatric_end_stage_failure = self.geriatric_adl_independent = None
        if self.imaging_not_done and self.imaging:
            self.imaging = []
        if self.biopsy_not_done:
            self.biopsy_history = []
        if not self.imaging_not_done and not self.imaging:
            raise ValueError("Record imaging or select 'imaging not done'.")
        for scan in self.imaging:
            if scan.date > self.evaluation_date:
                raise ValueError("Imaging date cannot be after the evaluation date.")
            if scan.date < self.date_of_birth:
                raise ValueError("Imaging date cannot be before the patient's date of birth.")
        if self.family_history_none:
            self.family_history = []
            self.family_history_reviewed = True
        if self.chest_radiation == YesNoUnknown.YES and not (
            self.chest_radiation_age or self.chest_radiation_years is not None
        ):
            raise ValueError("Enter the age or years for chest radiation.")
        if self.genetic_status == GeneticStatus.POSITIVE and self.genetic_gene is None:
            raise ValueError("Select the positive genetic test gene.")
        if self.genetic_gene == GeneticGene.OTHER and not self.genetic_gene_other:
            raise ValueError("Enter the other genetic test gene.")
        return self
