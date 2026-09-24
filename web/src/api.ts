import type { AuditRequest, AuditResponse, TiePageOut } from "./types";

export async function fetchHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const r = await fetch("/health", { signal });
    return r.ok;
  } catch {
    return false;
  }
}

export async function runAudit(req: AuditRequest): Promise<AuditResponse> {
  const r = await fetch("/api/audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    throw new Error(`API 异常：HTTP ${r.status}`);
  }
  return (await r.json()) as AuditResponse;
}

// Fetch one canonical-order page of tied solutions.  Stateless on the server:
// the audit input is resent so the full tie set never has to be transferred
// or materialised at once.
export async function fetchTies(
  req: AuditRequest,
  offset: number,
  limit: number,
): Promise<TiePageOut> {
  const r = await fetch("/api/audit/ties", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, offset, limit }),
  });
  if (!r.ok) {
    throw new Error(`API 异常：HTTP ${r.status}`);
  }
  return (await r.json()) as TiePageOut;
}
