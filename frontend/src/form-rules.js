export function validateReview(payload) {
  const errors = [];
  if (!payload.full_name) errors.push("Full name is required.");
  if (!payload.date_of_birth) errors.push("Date of birth is required.");
  if (!payload.national_id) errors.push("National ID is required.");
  return errors;
}

