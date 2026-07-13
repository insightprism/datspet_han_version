/**
 * The one client adapter for the Pet Maker backend (FastAPI on :19954).
 * Every endpoint URL lives here and nowhere else — pages and components
 * import these helpers instead of building URLs. Mirrors datsme_me's
 * web/src/lib/api.ts convention (NEXT_PUBLIC_API_URL from .env.local).
 */

// Use "localhost" (NOT the 127.0.0.1 literal) so the API host matches the
// host the DatsMe launch redirects the page to. The DPP launch cookie
// (datsme_launch, HttpOnly, credentials:"include") is set by the /launch response,
// so it is bound to the DATSPET_PUBLIC_URL host — "localhost" in dev, the same
// host as DATSPET_FRONTEND_URL — and the browser only sends it to fetch()es on
// that same host (cookies are host-scoped; ports don't matter, spelling does).
// Calling 127.0.0.1 here would be a different cookie host, the cookie would be
// dropped, and getDatsmeSession() would return launched:false (no Accept
// button). Keep this in sync with .env.local, DATSPET_FRONTEND_URL, and
// DATSPET_PUBLIC_URL — all must use the same hostname.
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:19954";

export interface JobStatus {
  id: string;
  name: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  breed_id: string | null;
  error: string | null;
}

export interface PetSummary {
  id: string;
  breed_id: string;
  display_name: string;
  created_at: number;
}

export async function generatePet(form: FormData): Promise<{ job_id: string }> {
  const r = await fetch(`${API_URL}/api/generate`, { method: "POST", body: form });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || data.error || "Server error");
  return data;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const r = await fetch(`${API_URL}/api/job/${encodeURIComponent(jobId)}`);
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || "Job not found");
  return data;
}

export async function listPets(): Promise<PetSummary[]> {
  const r = await fetch(`${API_URL}/api/pets`, { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load pets");
  return r.json();
}

// A pose offered by the motion menu (SPEC_MOTION_PROFILES §4.1). `required` poses
// (walk+idle) are always built and render locked-on in the selector.
export interface MotionPose {
  name: string;
  required: boolean;
  enabled: boolean;
}
export interface MotionMenu {
  profile: string;        // the resolved profile key (e.g. "quadruped", "serpentine")
  level: number;          // 1 breed .. 4 generic
  movement_class: string;
  poses: MotionPose[];    // only enabled + offerable poses (triggered ones hidden at launch)
}

// The pose menu for a species. `animal` is the keyword path (the design page's base
// pet species); a resolved profile drives which poses the pet can do.
export async function fetchMotions(animal: string): Promise<MotionMenu> {
  const r = await fetch(`${API_URL}/api/motions?animal=${encodeURIComponent(animal)}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error("Could not load the pose menu");
  return r.json();
}

export async function previewDesign(form: FormData): Promise<{ preview_id: string }> {
  const r = await fetch(`${API_URL}/api/preview`, { method: "POST", body: form });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || "Preview failed");
  return data;
}

export function previewImageUrl(previewId: string): string {
  return `${API_URL}/api/preview/${encodeURIComponent(previewId)}`;
}

export async function keepPet(petId: string): Promise<void> {
  const r = await fetch(`${API_URL}/api/pets/${encodeURIComponent(petId)}/keep`, {
    method: "POST",
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Could not save the pet");
  }
}

export async function deletePet(petId: string): Promise<void> {
  const r = await fetch(`${API_URL}/api/pets/${encodeURIComponent(petId)}`, {
    method: "DELETE",
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Could not remove the pet");
  }
}

export function petSheetUrl(petId: string): string {
  return `${API_URL}/api/pets/${encodeURIComponent(petId)}/sheet.png`;
}

export function petManifestUrl(petId: string): string {
  return `${API_URL}/api/pets/${encodeURIComponent(petId)}/manifest.json`;
}

export function petZipUrl(petId: string): string {
  return `${API_URL}/api/pets/${encodeURIComponent(petId)}/zip`;
}

// ---------------------------------------------------------------------------
// DatsMe partner (DPP) — only meaningful when launched from DatsMe. In
// standalone mode getDatsmeSession() returns {launched:false} and the UI keeps
// its normal Save-to-house flow.
// ---------------------------------------------------------------------------
export interface DatsmeSession {
  launched: boolean;
  user_id?: string;
  capabilities?: string[];
  cost?: number | null;
}

export async function getDatsmeSession(): Promise<DatsmeSession> {
  // credentials: the launch cookie is httponly, so it must ride cross-origin.
  const r = await fetch(`${API_URL}/api/datsme/session`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) return { launched: false };
  return r.json();
}

export interface AcceptResult {
  redirect_url?: string;
  queued?: boolean;
  message?: string;
}

export async function acceptPetToDatsme(petId: string): Promise<AcceptResult> {
  const r = await fetch(`${API_URL}/api/datsme/accept`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pet_id: petId }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    // 402 (credits), 409 (house full), 401 (relaunch) surface their detail.
    throw new Error(data.detail || "Could not send this pet to DatsMe");
  }
  return data;
}
