const $ = (id) => document.getElementById(id);
const form = $("intake");
function showClientFailure(message) {
  const box = $("form_error");
  if (box) { box.textContent = message; box.hidden = false; }
}
window.addEventListener("error", (event) => showClientFailure(`Form script error: ${event.message}`));
window.addEventListener("unhandledrejection", (event) => showClientFailure(`Form request error: ${event.reason?.message || event.reason || "Unknown error"}`));
const value = (id) => $(id)?.value?.trim() || null;
const number = (id) => value(id) === null ? null : Number(value(id));
const bool = (id) => !$(id) || $(id).value === "" ? null : $(id).value === "true";
const tri = (id) => value(id);
const radio = (name) => form.querySelector(`input[name="${name}"]:checked`)?.value ?? null;
const isoToday = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

$("evaluation_date").value = isoToday();
$("signed_date").value = isoToday();

function age() {
  if (!value("date_of_birth") || !value("evaluation_date")) return null;
  const birth = new Date(value("date_of_birth")), at = new Date(value("evaluation_date"));
  let years = at.getFullYear() - birth.getFullYear();
  if (at < new Date(at.getFullYear(), birth.getMonth(), birth.getDate())) years--;
  return years;
}

function updateAge() {
  const current = age();
  $("age_out").textContent = current ?? "—";
  const height = number("height_cm"), weight = number("weight_kg");
  $("bmi_out").textContent = height && weight ? (weight / ((height / 100) ** 2)).toFixed(1) : "—";
  $("age_out_top").textContent = current ?? "—";
  $("geriatric").hidden = current === null || current < 75;
}

function updateExamFields(side) {
  const abnormalInspection = value(`${side}_inspection`) === "Abnormal";
  const abnormalMass = value(`${side}_mass`) === "Abnormal";
  $(`${side}_inspection_finding`).hidden = !abnormalInspection;
  $(`${side}_mass_size`).hidden = !abnormalMass;
  $(`${side}_mass_mobility`).hidden = !abnormalMass;
  $(`${side}_mass_consistency`).hidden = !abnormalMass;
}

["r", "l"].forEach((side) => {
  $(`${side}_inspection`).addEventListener("change", () => updateExamFields(side));
  $(`${side}_mass`).addEventListener("change", () => updateExamFields(side));
  updateExamFields(side);
});

function addFamily() {
  const row = document.createElement("div");
  row.className = "grid repeat-row family-row";
  row.innerHTML = `<label class="field">Family side<select data-field="family_side"><option>Mother's side</option><option>Father's side</option><option>Unknown side</option></select></label>
    <label class="field">Relation<select data-field="relation" required><option value="">Select relation</option><option>Mother</option><option>Father</option><option>Sister</option><option>Brother</option><option>Daughter</option><option>Son</option><option>Maternal aunt</option><option>Paternal aunt</option><option>Grandmother</option><option>Other</option></select></label>
    <label class="field">Cancer type<select data-field="cancer_type"><option>Breast</option><option>Ovarian</option><option>Pancreatic</option><option>Prostate</option><option>Other</option></select></label>
    <label class="field">Age at diagnosis<input data-field="age_at_diagnosis" type="number" min="1" max="120" required></label>
    <button type="button" class="secondary remove">Remove</button>`;
  row.querySelector(".remove").onclick = () => row.remove();
  $("family_entries").appendChild(row);
}

function addImaging() {
  const row = document.createElement("div");
  row.className = "grid repeat-row imaging-row";
  row.innerHTML = `<input data-field="date" type="date" required><select data-field="modality"><option>Mammogram</option><option>DBT</option><option>MRI</option></select>
    <select data-field="density"><option value="">Density (MRI not applicable)</option><option>A</option><option>B</option><option>C</option><option>D</option></select>
    <input data-field="birads" type="number" min="0" max="6" placeholder="BI-RADS 0–6" required>
    <input data-field="radiologist_name" placeholder="Radiologist name" required><button type="button" class="secondary remove">Remove</button>`;
  row.querySelector(".remove").onclick = () => row.remove();
  const modality = row.querySelector('[data-field="modality"]');
  const density = row.querySelector('[data-field="density"]');
  const updateDensity = () => {
    const isMRI = modality.value === "MRI";
    density.hidden = isMRI;
    if (isMRI) density.value = "";
  };
  modality.addEventListener("change", updateDensity);
  updateDensity();
  $("imaging_entries").appendChild(row);
}

$("add_family").onclick = addFamily;
$("add_imaging").onclick = addImaging;
function updateFamilyMode() {
  const noFamilyHistory = $("family_history_none").checked;
  $("family_entries").hidden = noFamilyHistory;
  $("add_family").hidden = noFamilyHistory;
  if (noFamilyHistory) $("family_entries").replaceChildren();
}

$("family_history_none").addEventListener("change", (event) => {
  if (event.target.checked) $("family_history_reviewed").checked = false;
  updateFamilyMode();
});
$("family_history_reviewed").addEventListener("change", (event) => {
  if (event.target.checked) $("family_history_none").checked = false;
  updateFamilyMode();
});
updateFamilyMode();
$("imaging_not_done").addEventListener("change", (event) => {
  $("imaging_entries").hidden = event.target.checked;
  $("add_imaging").hidden = event.target.checked;
  if (event.target.checked) $("imaging_entries").replaceChildren();
});
$("date_of_birth").addEventListener("input", updateAge);
$("evaluation_date").addEventListener("input", updateAge);
$("height_cm").addEventListener("input", updateAge);
$("weight_kg").addEventListener("input", updateAge);
updateAge();
form.addEventListener("input", renderWarnings);
form.addEventListener("change", renderWarnings);

function exam(side) {
  return {
    inspection: value(`${side}_inspection`), inspection_finding: value(`${side}_inspection_finding`),
    mass: value(`${side}_mass`), mass_size_mm: number(`${side}_mass_size`), mass_mobility: value(`${side}_mass_mobility`),
    mass_consistency: value(`${side}_mass_consistency`), axillary_nodes: value(`${side}_nodes`)
  };
}

function repeated(container, fields) {
  return [...$(container).children].map(row => Object.fromEntries(fields.map(field => {
    const el = row.querySelector(`[data-field="${field}"]`);
    return [field, el.type === "number" ? (el.value === "" ? null : Number(el.value)) : (el.value || null)];
  })));
}

function payload() {
  const life = radio("life_expectancy"), serious = radio("serious_conditions");
  const geneticStatus = value("genetic_status");
  return {
    full_name: value("full_name"), date_of_birth: value("date_of_birth"), national_id: value("national_id"), phone: value("phone"),
    evaluation_date: value("evaluation_date"), presentation: radio("presentation") === null ? null : radio("presentation") === "true",
    lump_side: value("lump_side"), lump_duration: value("lump_duration"), nipple_discharge_side: value("nipple_discharge_side"),
    nipple_discharge_color: value("nipple_discharge_color"), skin_changes: [...document.querySelectorAll('input[name="skin_changes"]:checked')].map(input => input.value), pain_type: value("pain_type"), pain_severity: number("pain_severity"),
    race_ethnicity: value("race_ethnicity"), menarche_age: number("menarche_age"), menopausal_status: value("menopausal_status"), menopause_age: number("menopause_age"),
    parity: number("parity"), age_first_birth: number("age_first_birth"), ocp_use: value("ocp_use"), hrt_use: tri("hrt_use"), hrt_duration_years: number("hrt_duration_years"),
    chest_radiation: value("chest_radiation"), chest_radiation_age: number("chest_radiation_age"), chest_radiation_years: number("chest_radiation_years"),
    high_risk_biopsy: value("high_risk_biopsy"), lifetime_risk_pct: number("lifetime_risk_pct"), lifetime_risk_tool: value("lifetime_risk_tool"), lifetime_risk_date: value("lifetime_risk_date"), lifetime_risk_status: value("lifetime_risk_status"),
    genetic_status: geneticStatus, genetic_gene: value("genetic_gene"), genetic_gene_other: value("genetic_gene_other"), prior_biopsy_count: number("prior_biopsy_count"), prior_biopsy_atypia: value("prior_biopsy_atypia"),
    personal_breast_cancer: tri("personal_breast_cancer"), personal_mastectomy: tri("personal_mastectomy"), pregnancy_history: tri("pregnancy_history"), breastfeeding_history: tri("breastfeeding_history"),
    mri_pacemaker: tri("mri_pacemaker"), mri_implants: tri("mri_implants"), mri_kidney_problems: tri("mri_kidney_problems"), height_cm: number("height_cm"), weight_kg: number("weight_kg"),
    prior_breast_history: [...document.querySelectorAll('input[name="prior_breast_history"]:checked')].map(input => input.value), prior_breast_details: value("prior_breast_details"), family_history: repeated("family_entries", ["family_side", "relation", "cancer_type", "age_at_diagnosis"]), family_history_none: $("family_history_none").checked, family_history_reviewed: $("family_history_reviewed").checked,
    cbe_right: exam("r"), cbe_left: exam("l"), imaging: repeated("imaging_entries", ["date", "modality", "density", "birads", "radiologist_name"]), imaging_not_done: $("imaging_not_done").checked,
    plan: [...document.querySelectorAll("#plan_options input:checked")].map(input => input.value), warning_override_reason: value("warning_override_reason"), followup_months: number("followup_months"), examiner_name: value("examiner_name"), signed_date: value("signed_date"),
    notified_person: value("notified_person"), notified_at: value("notified_at"), patient_reached: bool("patient_reached"), biopsy_follow_up: value("biopsy_result") ? { result: value("biopsy_result"), date: value("biopsy_date") } : null,
    geriatric_life_expectancy_over_10y: life === null ? null : life === "true", geriatric_serious_medical_conditions: serious === null ? null : serious === "true"
  };
}

function showErrors(messages) {
  const box = $("form_error");
  box.replaceChildren();
  if (messages.length) {
    const list = document.createElement("ul");
    messages.forEach((message) => { const item = document.createElement("li"); item.textContent = message; list.appendChild(item); });
    box.appendChild(list);
  }
  box.hidden = !messages.length;
}

function showSuccess(message) {
  const box = $("form_success");
  box.textContent = message;
  box.hidden = !message;
}

function setConditionalValidity(p) {
  const familyError = !p.family_history_reviewed && !p.family_history_none
    ? "Select either no relevant family history or family history fully reviewed."
    : "";
  const imagingError = !p.imaging_not_done && !p.imaging.length
    ? "Add an imaging entry or select 'Imaging has not been done yet'."
    : "";
  $("family_history_none").setCustomValidity(familyError);
  $("imaging_not_done").setCustomValidity(imagingError);
  const planControl = document.querySelector("#plan_options input");
  if (planControl) planControl.setCustomValidity(p.plan.length ? "" : "Select a plan option.");
}

$("close_saved").addEventListener("click", () => $("saved_dialog").close());

function warningMessages(p) {
  const warnings = [];
  const abnormalExam = [p.cbe_right, p.cbe_left].some((exam) => exam.inspection === "Abnormal" || exam.mass === "Abnormal" || exam.axillary_nodes === "Abnormal");
  if (p.presentation === false && abnormalExam) warnings.push("Abnormal clinical examination is recorded for an asymptomatic presentation.");
  if (p.imaging.some((scan) => [4, 5, 6].includes(scan.birads)) && !p.plan.includes("Urgent biopsy referral")) warnings.push("BI-RADS 4–6 normally needs urgent biopsy referral.");
  if (p.imaging.some((scan) => scan.birads === 3) && p.plan.includes("Routine rescreening")) warnings.push("BI-RADS 3 normally needs short-term follow-up.");
  if (p.imaging.some((scan) => ["C", "D"].includes(scan.density)) && p.plan.includes("Routine rescreening")) warnings.push("Dense breast tissue may need supplemental imaging review.");
  if (p.plan.includes("Annual MRI") && [p.mri_pacemaker, p.mri_kidney_problems].includes("Yes")) warnings.push("MRI safety concern selected; confirm specialist clearance.");
  return warnings;
}

function renderWarnings() {
  const box = $("live_warnings");
  const warnings = warningMessages(payload());
  box.replaceChildren();
  if (warnings.length) {
    const list = document.createElement("ul");
    warnings.forEach((message) => { const item = document.createElement("li"); item.textContent = message; list.appendChild(item); });
    box.appendChild(list);
  }
  box.hidden = !warnings.length;
}

let saved = false;
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const p = payload();
  const errors = [];
  setConditionalValidity(p);
  if (!form.checkValidity()) {
    errors.push("Complete all required fields marked with *.");
    form.reportValidity();
  }
  if (warningMessages(p).length && !p.warning_override_reason) errors.push("Enter an override reason for the displayed warning.");
  showErrors(errors);
  showSuccess("");
  if (errors.length) return;
  const button = $("save_btn"); button.disabled = true; button.textContent = "Saving…";
  try {
    const response = await fetch("/api/intake", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const details = Array.isArray(body?.detail) ? body.detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(" > ")}: ${item.msg}`) : [body?.detail || `Server error (${response.status})`];
      throw new Error(details.join("; "));
    }
    showSuccess(`Saved patient ${body.patient_id}; server-calculated age: ${body.age}.`);
    $("saved_text").textContent = `Patient ${body.patient_id} was saved successfully. Server-calculated age: ${body.age}.`;
    $("saved_dialog").showModal();
    saved = true;
    form.querySelectorAll("input, select, button").forEach((control) => { if (control.id !== "save_btn") control.disabled = true; });
    button.textContent = "Saved";
  } catch (error) { showErrors([error instanceof Error ? error.message : "The server could not be reached."]); }
  finally { if (!saved) { button.disabled = false; button.textContent = "Save intake"; } }
});

const tocLinks = [...document.querySelectorAll(".toc a")];
const sectionObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      tocLinks.forEach((link) => link.classList.toggle("active", link.hash === `#${entry.target.id}`));
    }
  });
}, { rootMargin: "-20% 0px -70% 0px" });
document.querySelectorAll(".block").forEach((section) => sectionObserver.observe(section));
