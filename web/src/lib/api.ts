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

// The pose menu for a species. Two modes (SPEC_MOTION_PROFILES §4, §4.2):
//  - keyword path (General): pass `animal` (the base pet's species) → most-specific
//    keyword match decides the poses.
//  - pinned path (themed/catalog): pass a `profile` key → that profile's poses
//    exactly, so a curated breed animates at ≥ free-text fidelity.
// Pass one or the other; `profile` wins when both are given.
export async function fetchMotions(animal: string, profile?: string): Promise<MotionMenu> {
  const qs = profile
    ? `profile=${encodeURIComponent(profile)}`
    : `animal=${encodeURIComponent(animal)}`;
  const r = await fetch(`${API_URL}/api/motions?${qs}`, { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load the pose menu");
  return r.json();
}

// The base-animal catalog (SPEC_PET_DESIGNER_PLATFORM §4). Drives the landing-page
// tiles and each themed page's breed picker + instant base image. Read-only.
export interface CatalogBreed {
  key: string;
  label: string;
  motion_profile: string | null;  // the breed's pinned profile key (§4.2)
  base_image_url: string;         // path under API_URL; use catalogBaseImageUrl()
}
// An adoptable pre-made pet (§4.4). Adopting one skips generation (zero GPU).
export interface CatalogSample {
  key: string;
  preview_url: string | null;     // path under API_URL; null = no portrait
}
export interface CatalogAnimal {
  key: string;
  label: string;
  tagline: string;
  motion_profile: string | null;
  themed_page: string | null;     // /design/<themed_page>, or null = catalog-only
  breeds: CatalogBreed[];
  samples: CatalogSample[];
}

export async function fetchCatalog(): Promise<CatalogAnimal[]> {
  const r = await fetch(`${API_URL}/api/catalog`, { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load the animal catalog");
  const data = await r.json();
  return data.animals ?? [];
}

// The curated base sprite for a breed. The catalog returns a relative path
// (`/api/catalog/...`); this prefixes it with the API host for <img src>.
export function catalogBaseImageUrl(animal: string, breed: string): string {
  return `${API_URL}/api/catalog/${encodeURIComponent(animal)}/${encodeURIComponent(breed)}/base.png`;
}

// The portrait for an adoptable sample (§4.4). The catalog returns a relative
// preview_url; this prefixes it with the API host.
export function catalogSamplePreviewUrl(previewUrl: string): string {
  return `${API_URL}${previewUrl}`;
}

// Adopt a pre-made sample into the caller's house (§4.4) — zero-GPU. Returns the
// new draft pet id so the caller runs the normal Save/Accept flow. Credentialed:
// a DatsMe-launched user's adopt is scoped to them (the launch cookie rides).
export async function adoptSample(animal: string, sample: string): Promise<{ pet_id: string; display_name: string; breed_id: string }> {
  const r = await fetch(
    `${API_URL}/api/catalog/${encodeURIComponent(animal)}/samples/${encodeURIComponent(sample)}/adopt`,
    { method: "POST", credentials: "include" },
  );
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Could not adopt this pet");
  return data;
}

// The caller's OWN resolved tier entitlement (SPEC_PET_DESIGNER_PLATFORM §5.3).
// The browser never sees the whole tier table — only this slice. The pose
// selector caps + pricing hint come from here, not a client constant.
export interface Entitlement {
  tier: string;
  label: string;
  max_poses: number;
  extra_pose_slots: number;
  price_per_extra_pose: number;
  can_generate: boolean;
  can_adopt_samples: boolean;
  upsell: string;
  base_design_cost: number | null;   // host base charge; null if unknown
}

export async function fetchEntitlement(): Promise<Entitlement> {
  // Credentialed: a launched user's tier rides their launch cookie.
  const r = await fetch(`${API_URL}/api/entitlement`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) throw new Error("Could not load your plan");
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
