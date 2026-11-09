const $ = (id) => document.getElementById(id);
const form = $("intake");
// These fields are required even though their values are stored in the risk profile.
["height_cm", "weight_kg"].forEach((id) => {
  const control = $(id);
  if (!control) return;
  control.required = true;
  const label = control.closest("label");
  if (label && !label.querySelector(".req")) {
    const marker = document.createElement("span");
    marker.className = "req";
    marker.textContent = "required";
    label.insertBefore(marker, control);
  }
});
if (new URLSearchParams(window.location.search).get("new") === "1") form.reset();
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

function setField(id, valueToSet) {
  const field = $(id);
  if (field && valueToSet !== null && valueToSet !== undefined) field.value = valueToSet;
}

function setSelect(id, valueToSet) {
  const field = $(id);
  if (!field || valueToSet === null || valueToSet === undefined) return;
  if (![...field.options].some((option) => option.value === String(valueToSet))) field.add(new Option(valueToSet, valueToSet));
  field.value = valueToSet;
}

function historyLabel(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function hasHistoryValue(raw) {
  if (raw === null || raw === undefined || raw === "") return false;
  if (Array.isArray(raw)) return raw.some(hasHistoryValue);
  if (typeof raw === "object") return Object.values(raw).some(hasHistoryValue);
  return true;
}

function appendHistoryValue(container, raw) {
  if (Array.isArray(raw)) {
    raw.filter(hasHistoryValue).forEach((item) => {
      const nested = document.createElement("div"); nested.className = "history-nested";
      appendHistoryValue(nested, item); container.appendChild(nested);
    });
    return;
  }
  if (raw && typeof raw === "object") {
    Object.entries(raw).forEach(([key, valueToShow]) => {
      if (!hasHistoryValue(valueToShow)) return;
      const item = document.createElement("div"); item.className = "history-item";
      const label = document.createElement("strong"); label.textContent = historyLabel(key);
      const valueNode = document.createElement("span");
      item.append(label, valueNode); container.appendChild(item);
      if (typeof valueToShow === "object") appendHistoryValue(valueNode, valueToShow);
      else valueNode.textContent = String(valueToShow);
    });
    return;
  }
  const valueNode = document.createElement("span"); valueNode.textContent = String(raw); container.appendChild(valueNode);
}

function renderPreviousIntakes(history) {
  const block = $("previous_intakes");
  const cards = $("previous_intake_cards");
  if (!block || !cards) return;
  cards.replaceChildren();
  if (history.length <= 1) {
    block.hidden = true;
    return;
  }
  history.forEach((snapshot, index) => {
    const stored = typeof snapshot.payload === "string" ? JSON.parse(snapshot.payload) : (snapshot.payload || {});
    const submitted = stored.submitted || stored;
    const card = document.createElement("details");
    card.className = "history-card";
    const heading = document.createElement("summary");
    heading.textContent = `Encounter ${snapshot.encounter_id ?? index + 1} · ${snapshot.created_at ? new Date(snapshot.created_at).toLocaleString() : "Saved intake"}`;
    card.appendChild(heading);
    const grid = document.createElement("div");
    grid.className = "history-grid";
    const hidden = new Set(["idempotency_key", "phone", "full_name", "date_of_birth", "signed_date", "patient_id"]);
    Object.entries(submitted).forEach(([key, raw]) => {
      if (hidden.has(key) || !hasHistoryValue(raw)) return;
      const item = document.createElement("div"); item.className = "history-item history-top-item";
      const label = document.createElement("strong"); label.textContent = historyLabel(key);
      const valueNode = document.createElement("span"); item.append(label, valueNode);
      if (typeof raw === "object") appendHistoryValue(valueNode, raw);
      else valueNode.textContent = String(raw);
      grid.appendChild(item);
    });
    card.appendChild(grid);
    cards.appendChild(card);
  });
  block.hidden = false;
}

function prefillPatient(data) {
  const patient = data.patient || {};
  form.reset();
  $("family_entries")?.replaceChildren();
  $("imaging_entries")?.replaceChildren();
  $("breast_history_entries")?.replaceChildren();
  if ($("evaluation_date")) $("evaluation_date").value = isoToday();
  if ($("signed_date")) $("signed_date").value = isoToday();
  setField("patient_id", patient.patient_id);
  setField("full_name", patient.full_name);
  setField("date_of_birth", patient.date_of_birth);
  setField("phone", patient.phone);
  if ($("medical_history_yes")) $("medical_history_yes").checked = false;
  updateMedicalHistoryVisibility();
  updateAge();
  updateMaritalFields();
}

async function findExistingPatient() {
  const id = value("lookup_patient_id");
  const message = $("lookup_message");
  if (message) message.hidden = true;
  if (!id) {
    if (message) { message.textContent = "Enter a Patient ID."; message.hidden = false; }
    return;
  }
  try {
    const response = await fetch(`/api/patients/${encodeURIComponent(id)}`);
    if (response.status === 404) throw new Error("Record not found.");
    if (!response.ok) throw new Error("The patient record could not be loaded.");
    const data = await response.json();
    prefillPatient(data);
    renderPreviousIntakes(data.intake_history || []);
    setLookupEnabled(false);
    $("patient_lookup").close();
  } catch (error) {
    if (message) { message.textContent = error.message; message.hidden = false; }
  }
}

const lookupDialog = $("patient_lookup");
const lookupInput = $("lookup_patient_id");
const setLookupEnabled = (enabled) => { if (lookupInput) lookupInput.disabled = !enabled; };
lookupDialog.addEventListener("close", () => setLookupEnabled(false));
setLookupEnabled(false);
const intakeParams = new URLSearchParams(window.location.search);
if (intakeParams.get("lookup") === "1" || intakeParams.get("new") === "1") {
  setLookupEnabled(true);
  lookupDialog.showModal();
}
$("find_patient").addEventListener("click", findExistingPatient);
$("cancel_lookup").addEventListener("click", () => { setLookupEnabled(false); window.location.href = "/"; });
const selectIds = ["marital_status", "chest_radiation", "genetic_status", "breastfeeding_history", "geriatric_end_stage_failure", "geriatric_adl_independent"];
$("mri_pacemaker")?.closest(".subgroup")?.remove();

function organizePersonalHistory() {
  const personalSection = $("s2");
  const familySection = $("s3");
  const cbeSection = $("s4");
  const imagingSection = $("s5");
  const planSection = $("s6");
  const reviewSection = null;
  const source = personalSection?.querySelector(":scope > .grid");
  if (!source || personalSection.dataset.organized) return;
  personalSection.dataset.organized = "true";
  const field = (id) => $(id)?.closest(".field");
  ["race_ethnicity", "carrier_relative_status", "lifetime_risk_tool", "followup_months", "warning_override_reason", "notified_person", "notified_at", "patient_reached"].forEach((id) => field(id)?.remove());
  const personalHistory = [...personalSection.querySelectorAll(":scope > .subgroup")].find((item) => item.querySelector("h3")?.textContent.includes("Personal breast history"));
  const personalFields = personalHistory ? [...personalHistory.querySelectorAll(".field")].filter((field) => !["personal_breast_cancer", "personal_mastectomy"].includes(field.querySelector("select")?.id)) : [];
  const row = (title, nodes) => {
    const block = document.createElement("div"); block.className = "subgroup personal-organized";
    const heading = document.createElement("h3"); heading.textContent = title;
    const grid = document.createElement("div"); grid.className = "grid";
    nodes.filter(Boolean).forEach((node) => grid.appendChild(node));
    if (title) block.append(heading);
    block.append(grid); return block;
  };
  const bodyRow = row("Body measurements", [field("height_cm"), field("weight_kg"), field("bmi_out")?.closest(".field")]);
  const breastfeedingDuration = document.createElement("label"); breastfeedingDuration.className = "field"; breastfeedingDuration.innerHTML = 'Breastfeeding duration (years)<input id="breastfeeding_duration_years" type="number" min="0" max="30" step="0.5">';
  const breastfeedingField = field("breastfeeding_history");
  const obstetricRow = row("", [field("marital_status"), field("menarche_age"), field("menopausal_status"), field("menopause_age"), $("married_fields"), field("ocp_use"), field("hrt_use"), field("hrt_duration_years"), breastfeedingField, breastfeedingDuration]);
  const radiationRow = row("Chest radiation history", [field("chest_radiation"), field("chest_radiation_age"), field("chest_radiation_years")]);
  const geneticRow = row("Genetic history", [field("genetic_status"), field("genetic_gene")]);
  const geriatricRow = row("Geriatric Assessment (Only if Patient Age >= 75)", [field("geriatric_end_stage_failure"), field("geriatric_adl_independent")]);
  geriatricRow.id = "geriatric_assessment";
  const breastHistoryEntries = document.createElement("div"); breastHistoryEntries.id = "breast_history_entries";
  const addBreastEntry = document.createElement("button"); addBreastEntry.type = "button"; addBreastEntry.className = "secondary"; addBreastEntry.id = "add_breast_entry"; addBreastEntry.textContent = "Add breast entry";
  const breastHistoryRow = document.createElement("div"); breastHistoryRow.className = "subgroup personal-organized breast-history-group";
  breastHistoryRow.innerHTML = "<h3>Breast History</h3>";
  breastHistoryRow.append(breastHistoryEntries, addBreastEntry);
  const medicalHistory = document.createElement("div"); medicalHistory.className = "subgroup personal-organized";
  medicalHistory.innerHTML = '<h3>Medical History</h3><label class="choice-row"><input type="checkbox" id="medical_history_yes"> Yes</label><label class="field" id="medical_history_details_field" hidden>Medical history details<textarea id="medical_history_details" rows="3"></textarea></label>';
  personalHistory?.remove(); source.remove();

  const rename = (id, number, title) => { const block = $(id); block.querySelector("h2").innerHTML = `<span class="num">${number}</span>${title}`; return block; };
  rename("s1", 1, "Patient Demographics &amp; Baseline Data");
  const presentation = $("s1").querySelector("fieldset");
  const symptoms = $("s1").querySelectorAll(":scope > .grid")[1];
  const complaint = document.createElement("section"); complaint.className = "block"; complaint.id = "s2"; complaint.innerHTML = '<h2><span class="num">2</span>Chief Complaint &amp; Presenting Symptoms</h2>';
  if (presentation) complaint.appendChild(presentation); if (symptoms) complaint.appendChild(symptoms); $("s1").after(complaint);
  personalSection.id = "s4"; rename("s4", 4, "Personal Medical History"); personalSection.append(breastHistoryRow, medicalHistory, bodyRow, radiationRow, geneticRow, geriatricRow);
  const obstetric = document.createElement("section"); obstetric.className = "block"; obstetric.id = "s3"; obstetric.innerHTML = '<h2><span class="num">3</span>Obstetric &amp; Gynecological History</h2>'; obstetric.appendChild(obstetricRow); personalSection.before(obstetric);
  familySection.id = "s5"; rename("s5", 5, "Family History of Cancer");
  cbeSection.id = "s6"; rename("s6", 6, "Clinical Breast Examination (CBE)");
  imagingSection.id = "s7"; rename("s7", 7, "Imaging Assessment");
  planSection.id = "s8"; rename("s8", 8, "Clinical Plan &amp; Disposition");
  const nav = document.querySelector(".toc"); if (nav) { nav.replaceChildren(); [["s1", "1 Patient Demographics & Baseline Data"], ["s2", "2 Chief Complaint & Presenting Symptoms"], ["s3", "3 Obstetric & Gynecological History"], ["s4", "4 Personal Medical History"], ["s5", "5 Family History of Cancer"], ["s6", "6 Clinical Breast Examination (CBE)"], ["s7", "7 Imaging Assessment"], ["s8", "8 Clinical Plan & Disposition"]].forEach(([href, label]) => { const link = document.createElement("a"); link.href = `#${href}`; link.textContent = label; nav.appendChild(link); }); }
}

organizePersonalHistory();

function formatClinicalExamTable() {
  const section = $("s6");
  if (!section) return;
  const hint = section.querySelector(".hint");
  if (hint) hint.textContent = "Complete both breasts using the 4-quadrant clock-face layout. Not answered is not treated as normal.";
  const headers = section.querySelectorAll(".cbe thead th");
  ["Feature checked", "Right breast findings", "Left breast findings"].forEach((text, index) => { if (headers[index]) headers[index].textContent = text; });
  [["r_mass", "No Mass", "Mass Present"], ["l_mass", "No Mass", "Mass Present"], ["r_nodes", "Not Palpable", "Palpable"], ["l_nodes", "Not Palpable", "Palpable"]].forEach(([id, normal, abnormal]) => {
    const select = $(id);
    if (!select) return;
    const options = [...select.options];
    const normalOption = options.find((option) => option.value === "Normal");
    const abnormalOption = options.find((option) => option.value === "Abnormal");
    if (normalOption) normalOption.textContent = normal;
    if (abnormalOption) abnormalOption.textContent = abnormal;
  });
}

formatClinicalExamTable();
selectIds.forEach((id) => {
  const select = $(id);
  if (select && select.options[0]?.value !== "") select.insertBefore(new Option("Select...", ""), select.options[0]);
});
function isoToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

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
  updateMenopauseVisibility();
  updateHrtVisibility();
  updateGeriatricVisibility();
  const ageOutput = $("age_out");
  const bmiOutput = $("bmi_out");
  const topAgeOutput = $("age_out_top");
  if (ageOutput) ageOutput.textContent = current ?? "—";
  const height = number("height_cm"), weight = number("weight_kg");
  if (bmiOutput) bmiOutput.textContent = height && weight ? (weight / ((height / 100) ** 2)).toFixed(1) : "—";
  if (topAgeOutput) topAgeOutput.textContent = current ?? "—";
}

function updateGeriatricVisibility() {
  const visible = age() !== null && age() >= 75;
  const block = $("geriatric_assessment");
  if (block) block.hidden = !visible;
  ["geriatric_end_stage_failure", "geriatric_adl_independent"].forEach((id) => {
    const input = $(id); if (!input) return;
    input.closest(".field").hidden = !visible;
    if (!visible) input.value = "";
  });
}

function updateGeneticVisibility() {
  const visible = ["Positive", "Negative"].includes(value("genetic_status"));
  const field = $("genetic_gene_field");
  if (field) field.hidden = !visible;
  if (!visible && $("genetic_gene")) $("genetic_gene").value = "";
}

function updateMenopauseVisibility() {
  const current = age();
  const menopausalStatus = $("menopausal_status");
  const menopauseAge = $("menopause_age");
  const statusVisible = current !== null && current >= 40;
  const ageVisible = statusVisible && value("menopausal_status") === "Postmenopausal";
  if (menopausalStatus?.closest(".field")) menopausalStatus.closest(".field").hidden = !statusVisible;
  if (menopauseAge?.closest(".field")) menopauseAge.closest(".field").hidden = !ageVisible;
  if (!statusVisible) {
    if (menopausalStatus) menopausalStatus.value = "";
    if (menopauseAge) menopauseAge.value = "";
  } else if (!ageVisible && menopauseAge) {
    menopauseAge.value = "";
  }
}

function updateHrtVisibility() {
  const hrt = $("hrt_use"), duration = $("hrt_duration_years");
  const visible = age() !== null && age() >= 45 && age() <= 55;
  if (hrt?.closest(".field")) hrt.closest(".field").hidden = !visible;
  if (duration?.closest(".field")) duration.closest(".field").hidden = !visible || value("hrt_use") !== "Yes";
  if (!visible && hrt) hrt.value = "";
  if ((!visible || value("hrt_use") !== "Yes") && duration) duration.value = "";
}

function updateBreastfeedingVisibility() {
  const duration = $("breastfeeding_duration_years");
  if (duration?.closest(".field")) duration.closest(".field").hidden = value("breastfeeding_history") !== "Yes";
  if (value("breastfeeding_history") !== "Yes" && duration) duration.value = "";
}

function updateRadiationFields() {
  const visible = value("chest_radiation") === "Yes";
  ["chest_radiation_age", "chest_radiation_years"].forEach((id) => {
    const input = $(id);
    if (input) {
      input.closest(".field").hidden = !visible;
      if (!visible) input.value = "";
    }
  });
}

function updatePresentationFields() {
  const symptomatic = radio("presentation") === "true";
  ["lump_side", "lump_duration", "nipple_discharge_side", "nipple_discharge_color", "pain_type", "pain_severity"].forEach((id) => {
    const field = $(id);
    if (field) field.closest(".field").hidden = !symptomatic;
  });
  const dischargeColour = $("nipple_discharge_color")?.closest(".field");
  if (dischargeColour) dischargeColour.hidden = !symptomatic || !value("nipple_discharge_side");
  if (!symptomatic) {
    ["lump_side", "lump_duration", "nipple_discharge_side", "nipple_discharge_color", "pain_type", "pain_severity"].forEach((id) => { if ($(id)) $(id).value = ""; });
  }
}

document.querySelectorAll('input[name="presentation"]').forEach((input) => input.addEventListener("change", updatePresentationFields));
$("nipple_discharge_side")?.addEventListener("change", updatePresentationFields);
updatePresentationFields();
$("chest_radiation")?.addEventListener("change", updateRadiationFields);
updateRadiationFields();
$("genetic_status")?.addEventListener("change", updateGeneticVisibility);
updateGeneticVisibility();

$("hrt_use")?.addEventListener("change", () => {
  if (value("hrt_use") !== "Yes" && $("hrt_duration_years")) $("hrt_duration_years").value = "";
  updateHrtVisibility();
});
$("breastfeeding_history")?.addEventListener("change", updateBreastfeedingVisibility);
$("menopausal_status")?.addEventListener("change", updateMenopauseVisibility);

function updateMaritalFields() {
  const married = value("marital_status") === "Married";
  const marriedFields = $("married_fields");
  if (marriedFields) marriedFields.hidden = !married;
  const pregnancy = $("pregnancy_history"), breastfeeding = $("breastfeeding_history");
  if (pregnancy?.closest("label")) pregnancy.closest("label").remove();
  if (breastfeeding?.closest("label")) breastfeeding.closest("label").hidden = !married;
  if (!breastfeeding) return;
  breastfeeding.required = married;
  if (!married) {
    $("parity").value = "";
    $("age_first_birth").value = "";
    breastfeeding.value = "Unknown";
    if ($("breastfeeding_duration_years")) $("breastfeeding_duration_years").value = "";
  }
  updateBreastfeedingVisibility();
}

$("marital_status").addEventListener("change", updateMaritalFields);
updateMaritalFields();

function updateExamFields(side) {
  const abnormalInspection = value(`${side}_inspection`) === "Abnormal";
  const abnormalMass = value(`${side}_mass`) === "Abnormal";
  $(`${side}_inspection_finding`).hidden = !abnormalInspection;
  $(`${side}_nipple_discharge_color`).hidden = !abnormalInspection;
  $(`${side}_skin_change`).hidden = !abnormalInspection;
  $(`${side}_mass_size`).hidden = !abnormalMass;
  $(`${side}_mass_mobility`).hidden = !abnormalMass;
  $(`${side}_mass_consistency`).hidden = !abnormalMass;
  if (!abnormalInspection) $(`${side}_inspection_finding`).value = "";
  if (!abnormalInspection) {
    $(`${side}_nipple_discharge_color`).value = "";
    $(`${side}_skin_change`).value = "";
  }
  if (!abnormalMass) {
    $(`${side}_mass_size`).value = "";
    $(`${side}_mass_mobility`).value = "";
    $(`${side}_mass_consistency`).value = "";
  }
}

["r", "l"].forEach((side) => {
  $(`${side}_inspection`).addEventListener("change", () => updateExamFields(side));
  $(`${side}_mass`).addEventListener("change", () => updateExamFields(side));
  updateExamFields(side);
});

function addFamily() {
  const row = document.createElement("div");
  row.className = "grid repeat-row family-row";
  row.innerHTML = `<input type="hidden" data-field="family_side" value="Unknown side">
    <label class="field">Blood relative<select data-field="relation_degree" required><option value="">Select...</option><option value="1">First</option><option value="2">Second</option></select></label>
    <label class="field">Relation<input data-field="relation" required placeholder="e.g. Mother, sister, aunt"></label>
    <label class="field">Age at diagnosis<input data-field="age_at_diagnosis" type="number" min="1" max="120" required></label>
    <label class="field">Cancer type<select data-field="cancer_type" required><option value="">Select...</option><option>Breast</option><option>Ovarian</option></select></label>
    <label class="field">Known Genetic Mutations<select data-field="known_genetic_mutations" required><option value="">Select...</option><option>BRCA1</option><option>BRCA2</option><option>Negative</option><option>Unknown</option></select></label>
    <button type="button" class="secondary remove">Remove</button>`;
  row.querySelector(".remove").onclick = () => row.remove();
  $("family_entries").appendChild(row);
}

function addImaging() {
  const row = document.createElement("div");
  row.className = "grid repeat-row imaging-row";
  row.innerHTML = `<input data-field="date" type="date" required><select data-field="modality"><option value="Mammogram">Standard Mammo</option><option value="DBT">DBT (3D mammo)</option><option value="Ultrasound">Ultrasound</option><option value="MRI">MRI</option></select>
    <select data-field="density"><option value="">Density</option><option>A</option><option>B</option><option>C</option><option>D</option></select>
    <input data-field="birads" type="number" min="0" max="6" placeholder="BI-RADS 0–6" required>
    <button type="button" class="secondary remove">Remove</button>`;
  row.querySelector(".remove").onclick = () => row.remove();
  const modality = row.querySelector('[data-field="modality"]');
  const density = row.querySelector('[data-field="density"]');
  const updateDensity = () => {
    const densityNotApplicable = ["MRI", "Ultrasound"].includes(modality.value);
    density.hidden = densityNotApplicable;
    if (densityNotApplicable) density.value = "";
  };
  modality.addEventListener("change", updateDensity);
  updateDensity();
  $("imaging_entries").appendChild(row);
}

function addBreastEntry() {
  const row = document.createElement("div");
  row.className = "grid repeat-row breast-history-row";
  row.innerHTML = `<label class="field">Breast history<select data-field="type" required><option value="">Select...</option><option>None</option><option>Biopsy</option><option>Lumpectomy</option><option>Cyst Aspiration</option><option>Implants</option></select></label>
    <label class="field breast-entry-details">Details/Pathology findings<textarea data-field="details" rows="2"></textarea></label>
    <button type="button" class="secondary remove">Remove</button>`;
  const type = row.querySelector('[data-field="type"]');
  const details = row.querySelector('[data-field="details"]');
  const updateDetails = () => { const hasDetails = type.value && type.value !== "None"; row.querySelector(".breast-entry-details").hidden = !hasDetails; if (!hasDetails) details.value = ""; };
  type.addEventListener("change", updateDetails); updateDetails();
  row.querySelector(".remove").onclick = () => row.remove();
  $("breast_history_entries").appendChild(row);
}

$("add_breast_entry").addEventListener("click", addBreastEntry);

function updateMedicalHistoryVisibility() {
  const yes = $("medical_history_yes")?.checked;
  const field = $("medical_history_details_field");
  const details = $("medical_history_details");
  if (field) field.hidden = !yes;
  if (details) {
    details.required = Boolean(yes);
    if (!yes) details.value = "";
  }
}
$("medical_history_yes")?.addEventListener("change", updateMedicalHistoryVisibility);
updateMedicalHistoryVisibility();

$("add_family").onclick = addFamily;
$("add_imaging").onclick = addImaging;
function updateFamilyMode() {
  const noFamilyHistory = $("family_history_none").checked;
  $("family_entries").hidden = noFamilyHistory;
  $("add_family").hidden = noFamilyHistory;
  if (noFamilyHistory) $("family_entries").replaceChildren();
}

$("family_history_none").addEventListener("change", (event) => {
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
form.addEventListener("input", renderReview);
form.addEventListener("change", renderReview);

function exam(side) {
  return {
    inspection: value(`${side}_inspection`), inspection_finding: value(`${side}_inspection_finding`),
    nipple_discharge_color: value(`${side}_nipple_discharge_color`), skin_change: value(`${side}_skin_change`),
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
  const geneticStatus = value("genetic_status");
  return {
    full_name: value("full_name"), date_of_birth: value("date_of_birth"), patient_id: value("patient_id"), phone: value("phone"),
    evaluation_date: value("evaluation_date"), presentation: radio("presentation") === null ? null : radio("presentation") === "true",
    lump_side: value("lump_side"), lump_duration: value("lump_duration"), nipple_discharge_side: value("nipple_discharge_side"),
    nipple_discharge_color: value("nipple_discharge_color"), pain_type: value("pain_type"), pain_severity: number("pain_severity"),
    marital_status: value("marital_status"), menarche_age: number("menarche_age"), menopausal_status: value("menopausal_status"), menopause_age: number("menopause_age"),
    parity: value("marital_status") === "Married" ? number("parity") : null, age_first_birth: value("marital_status") === "Married" ? number("age_first_birth") : null, ocp_use: value("ocp_use"), hrt_use: value("hrt_use"), hrt_duration_years: number("hrt_duration_years"),
    chest_radiation: value("chest_radiation"), chest_radiation_age: number("chest_radiation_age"), chest_radiation_years: number("chest_radiation_years"),
    genetic_status: geneticStatus, genetic_gene: value("genetic_gene"), genetic_gene_other: value("genetic_gene_other"),
    personal_breast_cancer: "Unknown", personal_mastectomy: "Unknown", pregnancy_history: "Unknown", breastfeeding_history: value("marital_status") === "Married" ? tri("breastfeeding_history") : "Unknown", breastfeeding_duration_years: value("marital_status") === "Married" ? number("breastfeeding_duration_years") : null,
    height_cm: number("height_cm"), weight_kg: number("weight_kg"),
    breast_history: repeated("breast_history_entries", ["type", "details"]), medical_history_present: $("medical_history_yes").checked, medical_history_details: value("medical_history_details"), family_history: repeated("family_entries", ["family_side", "relation", "relation_degree", "cancer_type", "age_at_diagnosis", "known_genetic_mutations"]), family_history_none: $("family_history_none").checked, family_history_reviewed: false,
    cbe_right: exam("r"), cbe_left: exam("l"), imaging: repeated("imaging_entries", ["date", "modality", "density", "birads"]), imaging_not_done: $("imaging_not_done").checked,
    plan: [...document.querySelectorAll("#plan_options input:checked")].map(input => input.value), clinician_notes: value("clinician_notes"), examiner_name: value("examiner_name"), signed_date: value("signed_date"),
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

function controlLabel(control) {
  const fieldset = control.closest("fieldset");
  if (fieldset && (control.type === "radio" || control.type === "checkbox")) {
    const legend = fieldset.querySelector("legend");
    if (legend) return legend.textContent.replace(/\*/g, "").replace(/required/gi, "").trim();
  }
  const planOptions = control.closest("#plan_options");
  if (planOptions) return "Plan";
  const tableRow = control.closest("tr");
  if (tableRow) {
    const finding = tableRow.querySelector("th")?.textContent.trim();
    const cell = control.closest("td");
    const side = cell && [...tableRow.querySelectorAll("td")].indexOf(cell) === 0 ? "right" : "left";
    if (finding) return `${finding} (${side})`;
  }
  const label = control.closest("label");
  if (label) return label.textContent.replace(/\*/g, "").replace(/required/gi, "").trim();
  return control.getAttribute("aria-label") || control.id || "Unnamed field";
}

function missingFieldMessages() {
  const invalidControls = [...form.querySelectorAll("input, select, textarea")]
    .filter((control) => !control.disabled && !control.checkValidity());
  form.querySelectorAll("input, select, textarea").forEach((control) => {
    control.classList.toggle("invalid", invalidControls.includes(control));
  });
  const labels = [...new Set(invalidControls.map(controlLabel))];
  if (invalidControls.length) {
    invalidControls[0].scrollIntoView({ behavior: "smooth", block: "center" });
    invalidControls[0].focus({ preventScroll: true });
  }
  return labels;
}

function showSuccess(message) {
  const box = $("form_success");
  box.textContent = message;
  box.hidden = !message;
}

function setConditionalValidity(p) {
  const familyError = "";
  const imagingError = !p.imaging_not_done && !p.imaging.length
    ? "Add an imaging entry or select 'Imaging has not been done yet'."
    : "";
  $("family_history_none").setCustomValidity(familyError);
  $("imaging_not_done").setCustomValidity(imagingError);
  const planControl = document.querySelector("#plan_options input");
  if (planControl) planControl.setCustomValidity(p.plan.length ? "" : "Select a plan option.");
}

$("close_saved").addEventListener("click", () => { window.location.href = "/"; });

function warningMessages(p) {
  const warnings = [];
  const abnormalExam = [p.cbe_right, p.cbe_left].some((exam) => exam.inspection === "Abnormal" || exam.mass === "Abnormal" || exam.axillary_nodes === "Abnormal");
  if (p.presentation === false && abnormalExam) warnings.push("Abnormal clinical examination is recorded for an asymptomatic presentation.");
  if (p.imaging.some((scan) => [4, 5, 6].includes(scan.birads)) && !p.plan.includes("Urgent biopsy referral")) warnings.push("BI-RADS 4–6 normally needs urgent biopsy referral.");
  if (p.imaging.some((scan) => scan.birads === 3) && p.plan.includes("Routine rescreening")) warnings.push("BI-RADS 3 normally needs short-term follow-up.");
  if (p.imaging.some((scan) => ["C", "D"].includes(scan.density)) && p.plan.includes("Routine rescreening")) warnings.push("Dense breast tissue may need supplemental imaging review.");
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

function renderReview() {
  const p = payload();
  const review = $("review_content");
  if (!review) return;
  review.replaceChildren();
  const nippleDischarge = [p.nipple_discharge_side, p.nipple_discharge_color].filter(Boolean).join(" · ") || "None";
  const items = [
    ["Patient", p.full_name || "Not entered"],
    ["Patient ID", p.patient_id || "Not entered"],
    ["Presentation", p.presentation === null ? "Not selected" : (p.presentation ? "Symptomatic" : "Asymptomatic")],
    ["Lump", p.lump_side || "None"],
    ["Nipple discharge", nippleDischarge],
    ["Pain", p.pain_type || "None"],
    ["Imaging", p.imaging_not_done ? "Not done yet" : `${p.imaging.length} entr${p.imaging.length === 1 ? "y" : "ies"}`],
    ["Plan", p.plan.length ? p.plan.join(", ") : "Not selected"],
    ["Examiner", p.examiner_name || "Not entered"],
  ];
  items.forEach(([label, text]) => {
    const item = document.createElement("div"); item.className = "review-item";
    const heading = document.createElement("strong"); heading.textContent = label;
    const valueNode = document.createElement("span"); valueNode.textContent = text;
    item.append(heading, valueNode); review.appendChild(item);
  });
}

renderReview();

let saved = false;
function renderSavedResult(body) {
  const risk = body.risk_assessment || {};
  const alertText = risk.alert_trigger || ({ High: "CRITICAL HIGH-RISK CARE ROUTING ACTIVE", Medium: "DENSE TISSUE MASKING RISK / SHORT-INTERVAL TRACKING", Low: "ROUTINE SCREENING ELIGIBLE" }[risk.tier] || "RISK ASSESSMENT PENDING");
  $("risk_alert").textContent = alertText;
  $("risk_alert").className = `risk-${String(risk.tier || "incomplete").toLowerCase()}`;
  const riskText = risk.label || (risk.tier === "Low" ? "Low (lifetime risk not assessed)" : risk.tier) || "Incomplete";
  $("risk_label").textContent = riskText;
  $("risk_label").className = `risk-${String(risk.tier || "incomplete").toLowerCase()}`;
  const reasons = $("risk_reasons"); reasons.replaceChildren();
  (risk.reasons || []).forEach((reason) => { const li = document.createElement("li"); li.textContent = reason; reasons.appendChild(li); });
  if (!reasons.children.length) { const li = document.createElement("li"); li.textContent = "No triggering factors recorded."; reasons.appendChild(li); }
  const plan = $("doctor_plan"); plan.replaceChildren();
  (body.doctor_plan || []).forEach((item) => { const li = document.createElement("li"); li.textContent = item.due_date ? `${item.option} — due ${item.due_date}` : item.option; plan.appendChild(li); });
  (body.doctor_plan || []).forEach((item, index) => {
    if (!item.recurrence || !plan.children[index]) return;
    const recurrence = document.createElement("small"); recurrence.textContent = item.recurrence;
    plan.children[index].appendChild(recurrence);
  });
  if (!plan.children.length) { const li = document.createElement("li"); li.textContent = "No plan selected."; plan.appendChild(li); }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const p = payload();
  const errors = [];
  setConditionalValidity(p);
  if (!form.checkValidity()) {
    const missing = missingFieldMessages();
    errors.push(missing.length
      ? `Please complete: ${missing.join(", ")}.`
      : "Complete all required fields marked with *.");
    form.reportValidity();
  }
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
    renderSavedResult(body);
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
