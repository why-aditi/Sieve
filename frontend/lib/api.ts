import type { Analysis } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL;

export class ApiError extends Error {}

/** Used only by the "connect your own" paths. The demo never comes through
 *  here — it is bundled, so a cold or dead backend cannot break what the judge
 *  sees. */
async function post(path: string, body: BodyInit, headers: HeadersInit): Promise<Analysis> {
  if (!API) {
    throw new ApiError(
      "The analysis service isn't configured for this deployment. The sample data still works.",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { method: "POST", body, headers });
  } catch {
    // Render's free tier sleeps; the first request after idle can take ~50s.
    throw new ApiError(
      "Couldn't reach the analysis service. It may be waking up — try again in a moment.",
    );
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the status-code message */
    }
    throw new ApiError(detail);
  }
  return response.json();
}

export const ingestCsv = (file: File) =>
  post("/ingest/csv", file, { "Content-Type": "text/csv" });
