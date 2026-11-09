export function renderReview(container, result) {
  const assessment = result.assessment;
  container.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = "Review";
  const summary = document.createElement("p");
  summary.textContent = `${assessment.tier} · ${assessment.urgency}`;
  container.append(heading, summary);
}

