export function buildPayload(form) {
  return Object.fromEntries(new FormData(form).entries());
}

