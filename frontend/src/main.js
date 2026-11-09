import { preview } from "./api.js";
import { buildPayload } from "./payload.js";
import { validateReview } from "./form-rules.js";
import { renderReview } from "./review.js";

const app = document.querySelector("#app");
const form = document.createElement("form");
form.innerHTML = `<p>This module is ready for the existing intake template.</p>
  <button type="button">Preview assessment</button><section aria-live="polite"></section>`;
form.querySelector("button").addEventListener("click", async () => {
  const payload = buildPayload(form);
  const errors = validateReview(payload);
  if (errors.length) return renderReview(form.querySelector("section"), { assessment: { tier: errors.join(" "), urgency: "Error" } });
  try {
    renderReview(form.querySelector("section"), await preview(payload));
  } catch (error) {
    renderReview(form.querySelector("section"), { assessment: { tier: error.message, urgency: "Error" } });
  }
});
app.replaceChildren(form);

