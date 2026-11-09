export async function preview(payload) {
  const response = await fetch("/api/intake/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({ detail: "Invalid server response" }));
  if (!response.ok) throw new Error(body.detail || "Preview failed");
  return body;
}

