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
// Empty (or unset-in-dev) → relative same-origin calls (`/api/...`), which the
// next.config dev proxy forwards to the backend. This keeps the launch cookie
// first-party so Firefox stores it (a cross-origin Secure cookie over plain
// http://localhost is dropped by Firefox). In prod the static export sets
// NEXT_PUBLIC_API_URL to the same-origin public host (nginx serves /api there).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").trim();

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
  // Already in the caller's DatsMe house — stamped by a push Accept or by the
  // host's post-import ack. Information, not a gate: re-importing is free and
  // updates in place (SPEC_DPP_DATA_TRANSFER_CHANNEL §3.3).
  in_datsme: boolean;
  // Visible to this caller but not yet owned by them (an unclaimed local pet).
  // The house shows these; /partner/export/{user_id} is exact-match and does not,
  // so they must be claimed before we hand the user to DatsMe's import page or
  // they silently vanish from it (SPEC_DATSPET_HOUSE_ADOPT §2).
  claimable: boolean;
}

// Bind unclaimed local pets to the launched caller. Called with the ids the user
// selected before linking out to the import page — never speculatively.
export async function claimPets(petIds: string[]): Promise<{ claimed: string[] }> {
  const r = await fetch(`${API_URL}/api/pets/claim`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pet_ids: petIds }),
  });
  if (!r.ok) throw new Error("Could not prepare those pets for DatsMe");
  return r.json();
}

export async function generatePet(form: FormData): Promise<{ job_id: string }> {
  const r = await fetch(`${API_URL}/api/generate`, { method: "POST", body: form });
  // Check status before parsing: a non-JSON error body (proxy HTML, empty 502)
  // must surface the real failure, not an opaque JSON.parse error.
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || data.error || "Server error");
  }
  return r.json();
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const r = await fetch(`${API_URL}/api/job/${encodeURIComponent(jobId)}`);
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Job not found");
  }
  return r.json();
}

export async function listPets(): Promise<PetSummary[]> {
  const r = await fetch(`${API_URL}/api/pets`, { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load pets");
  return r.json();
}

// The caller's house shape (SPEC house-scaling): the cap, the display page size,
// and their current saved count. Config, not collection — separate from listPets
// because it changes for a different reason (an ops knob vs a new pet). Drives the
// "N / max" readout and the client-side pager. Server-owned so page size / cap are
// never client constants.
export interface HouseConfig {
  max_pets: number;
  page_size: number;
  count: number;
}

export async function getHouseConfig(): Promise<HouseConfig> {
  const r = await fetch(`${API_URL}/api/house`, { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load house settings");
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

// A curated base option: one breed carrying the animal (key + label) it belongs
// to, so a flat cross-animal list stays self-describing. The single definition
// consumed by both the API helper below and the PetDesigner component.
export interface CatalogBaseOption extends CatalogBreed {
  animal: string;         // the animal key this breed belongs to
  animalLabel?: string;   // for grouping/labeling in a flat list
}

// A flat list of every curated base across animals — each breed carries its
// animal (key + label). Drives the General designer's "Pet to redesign" list
// (all curated bases, no house-pet clutter).
export function catalogBaseOptions(animals: CatalogAnimal[]): CatalogBaseOption[] {
  const out: CatalogBaseOption[] = [];
  for (const a of animals) {
    for (const b of a.breeds) {
      out.push({ ...b, animal: a.key, animalLabel: a.label });
    }
  }
  return out;
}

// NOTE — adopt-a-sample has no client helper any more.
//
// `catalogSamplePreviewUrl` and `adoptSample` were <SampleGallery>'s, and the gallery
// went with the themed pages (SPEC_PET_DESIGNER_FLOW §11). They are removed rather than
// kept warm: dead client code that looks live is worse than an absent helper, and the
// six lines cost nothing to write again.
//
// `POST /api/catalog/{animal}/samples/{sample}/adopt` still EXISTS. Platform §4.4 calls
// it the zero-GPU business lever — free users steered to adopt, paid users generate — so
// it is kept deliberately rather than lost by attrition. But be clear about what it is:
//
//   no UI       SampleGallery was its only entry point, and it went with the themed
//               pages (SPEC_PET_DESIGNER_FLOW §11).
//   no content  catalog.json defines no `samples` at all, so `_samples_dir()` returns
//               None for every animal and `list_samples()` returns []. It rendered
//               nothing even when the gallery existed.
//   NO TESTS    (An earlier version of this comment claimed "still tested server-side".
//               That was false — grep finds zero. Said plainly now: reviving this means
//               writing them.)
//
// So it is three-quarters dead, and reviving it needs all three: promote the one real
// sample (staged at _candidates/dog/samples/friendlypup.zip, commit b64dc3c — a path
// _samples_dir never looks at), build an entry point, and test the endpoint.
//
// `CatalogSample` / `CatalogAnimal.samples` below stay: /api/catalog really does return
// the field, and the type must model the response, not the consumer.

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

// ---------------------------------------------------------------------------
// Motion-profile admin (SPEC_MOTION_PROFILE_ADMIN §4). Every call is credentialed
// (the datspet_admin cookie rides); a 401 means "not an admin" → bounce to the
// host admin-launch. The one adapter owns these URLs like every other endpoint.
// ---------------------------------------------------------------------------
export const CANONICAL_POSES = [
  "walk", "idle", "run", "sleep", "sit", "eat", "jump", "play", "swim", "fly",
] as const;
export const REQUIRED_POSES = ["walk", "idle"] as const;
export const POSE_ROLES = ["rest", "active", "timed", "triggered"] as const;

export interface MotionPoseSpec {
  enabled: boolean;
  runtime_role?: string | null;
  action?: string | null;
  suffix?: string;
}
export interface MotionProfileFile {
  key: string;
  level: number;
  movement_class: string;
  keywords: string[];
  poses: Record<string, MotionPoseSpec>;
}
export interface MotionProfileSummary {
  key: string;
  label: string;
  level: number;
  movement_class: string;
  enabled_poses: string[];
  keyword_count: number;
  is_default: boolean;
  pinned_by: string[];
}
export interface MotionAdminList {
  default: string;
  writable: boolean;
  profiles: MotionProfileSummary[];
}
export interface MotionProfileDetail {
  profile: MotionProfileFile;
  label: string;
  is_default: boolean;
  pinned_by: string[];
  writable: boolean;
}

// Thrown by the admin calls; carries the server's validation error list on a 422.
export class MotionAdminError extends Error {
  status: number;
  errors: string[];
  constructor(message: string, status: number, errors: string[] = []) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

async function adminFetch(path: string, init?: RequestInit) {
  const r = await fetch(`${API_URL}/api/admin/motions${path}`, {
    credentials: "include",
    cache: "no-store",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (r.ok) return r.json().catch(() => ({}));
  const data = await r.json().catch(() => ({}));
  // 422 detail = {error, errors[]}; other errors carry a string/detail.
  const detail = data.detail;
  const errors = detail && typeof detail === "object" ? detail.errors ?? [] : [];
  const msg = detail && typeof detail === "object" ? (detail.error ?? "request failed")
    : (detail ?? "request failed");
  throw new MotionAdminError(String(msg), r.status, errors);
}

export const motionAdmin = {
  list: (): Promise<MotionAdminList> => adminFetch(""),
  get: (key: string): Promise<MotionProfileDetail> => adminFetch(`/${encodeURIComponent(key)}`),
  create: (profile: MotionProfileFile, label: string) =>
    adminFetch("", { method: "POST", body: JSON.stringify({ profile, label }) }),
  update: (key: string, profile: MotionProfileFile, label: string) =>
    adminFetch(`/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ profile, label }) }),
  remove: (key: string) =>
    adminFetch(`/${encodeURIComponent(key)}`, { method: "DELETE" }),
  duplicate: (key: string, new_key: string, new_label: string): Promise<{ profile: MotionProfileFile }> =>
    adminFetch(`/${encodeURIComponent(key)}/duplicate`, { method: "POST", body: JSON.stringify({ new_key, new_label }) }),
};

// ── The reference layer (SPEC_PET_DESIGNER_FLOW §7.4) ────────────────────────
//
// ONE record shape, three endpoints. Every way of starting a pet ends in the same
// artifact — a reference still — so nothing downstream branches on where it came
// from (§6). `previewReference` takes a reference and returns a reference (§6.1):
// two handle types would force every caller to branch on which kind it holds.
//
// All of these are credentialed: references are owner-scoped (§7.3), so the DPP
// launch cookie must ride or a launched user cannot read their own box.

export interface PetReference {
  reference_id: string;
  image_url: string;              // path under API_URL — use referenceImageUrl()
  description: string;            // the SHORT species phrase ("purple corgi"), §7.3
  display_name: string;
  motion_profile: string | null;  // pinned at fill time; null → keyword-resolved
  // Recorded for support/telemetry ONLY. Do NOT branch on it: "the engine reads
  // the record and acts; it never asks where the record came from" (§6). Rev.1 of
  // the spec relaxed a design guard on source === "txt2img" and broke its own rule.
  source: "catalog" | "txt2img" | "upload" | "design";
  min_strength: number | null;    // the clamp that was applied, so the UI can say so
  generated: boolean;             // false = a curated cache hit, free and instant
}

export interface DesignAxisOption {
  key: string;
  label: string;
  is_default: boolean;
}

// One design axis (SPEC_PET_DESIGN_AXES §4): a curated vocabulary the server
// hands us pre-filtered by the animal's surface — a bird receives plumage and
// never coat, an unknown creature only the universal axes. The browser renders
// what it is handed; it holds NO animal logic and never sees prompt wording.
export interface DesignAxis {
  axis: string;
  label: string;
  kind: "universal" | "surface";
  default: string;
  options: DesignAxisOption[];
}

async function referenceCall(path: string, form: FormData): Promise<PetReference> {
  const r = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    // FastAPI answers an UNMATCHED ROUTE with exactly {"detail":"Not Found"}, which
    // is indistinguishable from "that resource is missing" if you just surface
    // `detail`. In practice it means the backend predates this endpoint — a dev
    // server that hasn't been restarted — and a bare "Not Found" under a button
    // reads as "the button is broken". Name the real cause.
    if (r.status === 404 && data.detail === "Not Found") {
      throw new Error(
        `The backend doesn't have ${path} — it probably needs a restart to pick up new endpoints.`,
      );
    }
    throw new Error(data.detail || `That didn't work (${r.status})`);
  }
  return r.json();
}

// Step 1 — fill the box. Exactly one of: a curated breed, a free-text animal, or
// an uploaded photo. The server decides the mechanism (copy a curated base.png vs
// draw one); the client never chooses it, and `generated` reports what happened.
export function createReference(form: FormData): Promise<PetReference> {
  return referenceCall("/api/reference", form);
}

// Step 3 — redraw a reference toward a design. Returns a NEW reference.
export function previewReference(form: FormData): Promise<PetReference> {
  return referenceCall("/api/preview", form);
}

export function referenceImageUrl(referenceId: string): string {
  return `${API_URL}/api/reference/${encodeURIComponent(referenceId)}.png`;
}

// The design-step vocabulary, filtered server-side by the reference's resolved
// surface (SPEC_PET_DESIGN_AXES §4). Without a referenceId the server returns
// the universal axes — enough for the flow to reason about defaults before an
// animal is chosen. Credentialed: the reference is owner-scoped (§7.3).
export async function fetchDesignAxes(referenceId?: string): Promise<{ axes: DesignAxis[] }> {
  const qs = referenceId ? `?reference_id=${encodeURIComponent(referenceId)}` : "";
  const r = await fetch(`${API_URL}/api/design-axes${qs}`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!r.ok) throw new Error("Could not load design options");
  return r.json();
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
  display_name?: string | null;  // the signed-in user's DatsMe name (nm claim), for the nav
  capabilities?: string[];
  cost?: number | null;
  // Front-door fields (SPEC_DATSPET_FRONT_DOOR §3.2). Present on every response.
  integrated?: boolean;         // wired to a DatsMe host? false = standalone (no DatsMe buttons)
  signin_url?: string | null;   // where "Sign in with DatsMe" points (host login-launch bounce)
  signup_url?: string | null;   // where "Create a DatsMe account" points (host /signup)
  // Where the house's Adopt action hands off: `${import_url}?items=a,b,c`. Built
  // server-side — the partner slug is env-overridable, so the browser must never
  // assemble this itself (SPEC_DATSPET_HOUSE_ADOPT §0.6).
  import_url?: string | null;
  admin?: boolean;              // a valid admin session is present (show the Admin toolbar link)
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

// End the DatsPet session (clears the launch + admin cookies host-side). The
// DatsMe session itself is managed on DatsMe (front-door §3.3).
export async function datsmeLogout(): Promise<void> {
  await fetch(`${API_URL}/api/datsme/logout`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {});
}

export interface AcceptResult {
  redirect_url?: string;
  queued?: boolean;
  message?: string;
}

// Carries the HTTP status so the UI can act on it — notably 401, which means the
// launch token expired and the user needs to re-launch before Accept can authorize.
export class AcceptError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
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
    // 402 (credits), 409 (house full), 401 (relaunch) surface their detail. The
    // detail may be a STRING or a structured object ({error, detail, hint} from a
    // host validation failure) — extract a readable message, never "[object Object]".
    const d = data.detail;
    const msg = typeof d === "string" ? d
      : d && typeof d === "object" ? (d.detail || d.error || JSON.stringify(d))
      : "Could not send this pet to DatsMe";
    throw new AcceptError(msg, r.status);
  }
  return data;
}
