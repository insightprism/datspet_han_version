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
// dropped, and getDatsmeSession() would return launched:false (no Adopt
// button). Keep this in sync with .env.local, DATSPET_FRONTEND_URL, and
// DATSPET_PUBLIC_URL — all must use the same hostname.
// Empty (or unset-in-dev) → relative same-origin calls (`/api/...`), which the
// next.config dev proxy forwards to the backend. This keeps the launch cookie
// first-party so Firefox stores it (a cross-origin Secure cookie over plain
// http://localhost is dropped by Firefox). In prod the static export sets
// NEXT_PUBLIC_API_URL to the same-origin public host (nginx serves /api there).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").trim();

/** Every request to our backend goes through here, so ONE place reacts to a
 * lapsed launch session (SPEC_DATSPET_FEDERATED_SESSION §5.3).
 *
 * A 401 carrying `detail.code === "session_stale"` means the user is still signed
 * in on DatsMe — only our copy of the assertion aged out — so the right response
 * is a silent re-launch, not an error the user has to read. Handled here rather
 * than at each call site because the renewal has a loop guard, and a guard that
 * has to be remembered in twenty places is a guard that gets forgotten in one.
 *
 * The response is returned unchanged either way: the navigation is already in
 * flight, and the caller's own error handling stays exactly as it was.
 */
async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(url, init);
  if (r.status === 401) {
    // clone(): peeking at the body must not consume it for the caller.
    const body = await r.clone().json().catch(() => null);
    handleSessionStale(r.status, body);
  }
  return r;
}

export interface JobStatus {
  id: string;
  name: string;
  status: "queued" | "running" | "done" | "error" | "canceled";
  progress: number;
  message: string;
  breed_id: string | null;
  error: string | null;
}

export interface PetSummary {
  id: string;
  breed_id: string;
  display_name: string;
  // The owner's FIRST name for the pet (null = unnamed). Display composes
  // "«pet_name» «animal»" via lib/petName.composePetName.
  pet_name: string | null;
  created_at: number;
  // Already in the caller's DatsMe house — stamped by the host's post-import ack.
  // Information, not a gate: re-importing is free and updates in place
  // (SPEC_DPP_DATA_TRANSFER_CHANNEL §3.3).
  sent_to_datsme: boolean;
  // This caller's own pet, still held under their browser's ANONYMOUS owner id
  // rather than a DatsMe user id — i.e. designed before signing in. The house
  // shows these; /partner/export/{user_id} is exact-match and does not, so they
  // must be claimed before we hand the user to DatsMe's import page or they
  // silently vanish from it (SPEC_DATSPET_HOUSE_ADOPT §2,
  // SPEC_DATSPET_FEDERATED_SESSION §4.5).
  claimable: boolean;
  // A pet the user DESIGNED, so the donate door would accept it
  // (SPEC_PET_STORE §10.1 gate 3). A projected column like the two above, not
  // a gate: the door re-checks it server-side. The other two gates — a DatsMe
  // identity and the entitlement — are request-scoped and cannot be answered
  // from a row, so the page ANDs them in. Getting that wrong shows a button
  // that 403s, never a donation that should not have happened.
  donatable: boolean;
}

// Bind unclaimed local pets to the launched caller. Called with the ids the user
// selected before linking out to the import page — never speculatively.
/** A finished build the caller never answered — the way back to a pet that a
 *  navigation interrupted. Newest first; the designer offers the newest.
 *  See GET /api/pets/unsaved for why this is not merged into listPets(). */
export interface UnsavedPet {
  id: string;
  breed_id: string;
  display_name: string;
  created_at: number;
}

export async function listUnsavedPets(): Promise<UnsavedPet[]> {
  const r = await apiFetch(`${API_URL}/api/pets/unsaved`, { credentials: "include" });
  if (!r.ok) return [];   // never block the designer on this — it is an offer, not a gate
  return r.json();
}

export async function claimPets(petIds: string[]): Promise<{ claimed: string[] }> {
  const r = await apiFetch(`${API_URL}/api/pets/claim`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pet_ids: petIds }),
  });
  if (!r.ok) throw new Error("Could not prepare those pets for DatsMe");
  return r.json();
}

export async function generatePet(form: FormData): Promise<{ job_id: string }> {
  const r = await apiFetch(`${API_URL}/api/generate`, { method: "POST", body: form });
  // Check status before parsing: a non-JSON error body (proxy HTML, empty 502)
  // must surface the real failure, not an opaque JSON.parse error.
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || data.error || "Server error");
  }
  return r.json();
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const r = await apiFetch(`${API_URL}/api/job/${encodeURIComponent(jobId)}`);
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Job not found");
  }
  return r.json();
}

// User-initiated Stop (§11). credentials: "include" so the DatsMe launch cookie travels for the
// owner check. Best-effort/idempotent server-side — a job that already finished returns terminal.
export async function stopJob(jobId: string): Promise<void> {
  const r = await apiFetch(`${API_URL}/api/job/${encodeURIComponent(jobId)}/stop`, {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Could not stop the build");
  }
}

export async function listPets(): Promise<PetSummary[]> {
  const r = await apiFetch(`${API_URL}/api/pets`, { cache: "no-store" });
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
  const r = await apiFetch(`${API_URL}/api/house`, { cache: "no-store" });
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
  const r = await apiFetch(`${API_URL}/api/motions?${qs}`, { cache: "no-store" });
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
export interface CatalogAnimal {
  key: string;
  label: string;
  tagline: string;
  motion_profile: string | null;
  breeds: CatalogBreed[];
}

export async function fetchCatalog(): Promise<CatalogAnimal[]> {
  const r = await apiFetch(`${API_URL}/api/catalog`, { cache: "no-store" });
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

// The Pet Store (SPEC_PET_STORE §3.1, §6) — the DB-backed shelf of ready-made
// pets that replaced the file-sample surface (§8; the old adopt-a-sample
// helpers stood here). Browsing is anonymous; adopting is a COPY, not a
// purchase: it puts a draft in the caller's house, and the money happens
// later, on the host, through the same checkout a designed pet uses
// (handOffToDatsme). Nothing here prices anything (§0.5.1).

export interface StoreListing {
  id: string;
  display_name: string;
  breed_id: string;
  animal: string;                 // the filter-chip key ("cat")
  description: string;
  tags: string[];
  pose_count: number;
  poses: string[];
  created_at: number;
  preview_url: string;            // path under API_URL; use storePreviewUrl()
}

export async function fetchStoreListings(): Promise<StoreListing[]> {
  const r = await apiFetch(`${API_URL}/api/store`, { cache: "no-store" });
  if (!r.ok) throw new Error("Could not load the pet store");
  const data = await r.json();
  return data.pets ?? [];
}

/** The card portrait. `preview_url` is a path under API_URL, so it needs the
 *  same prefixing every other asset does. */
export function storePreviewUrl(storeId: string): string {
  return `${API_URL}/api/store/${encodeURIComponent(storeId)}/preview.png`;
}

/** The sprite sheet + its geometry, for animating a listing in place (§6.4).
 *  The pet equivalents (`petSheetUrl`/`petManifestUrl`) are owner-scoped; these
 *  are public and shelf-gated, because a shop card has no signed-in caller. */
export function storeSheetUrl(storeId: string): string {
  return `${API_URL}/api/store/${encodeURIComponent(storeId)}/sheet.png`;
}

export function storeManifestUrl(storeId: string): string {
  return `${API_URL}/api/store/${encodeURIComponent(storeId)}/manifest.json`;
}

export interface AdoptedStorePet {
  pet_id: string;
  display_name: string;
  breed_id: string;
}

/** Copy a store pet into the caller's house as a draft. Zero GPU, instant.
 *
 * Scoped like every other write: the pet lands under the caller's owner id,
 * anonymous or DatsMe (SPEC_DATSPET_FEDERATED_SESSION §4.5), which is what lets a
 * signed-out visitor adopt first and sign in after.
 */
export async function adoptStorePet(storeId: string): Promise<AdoptedStorePet> {
  const r = await apiFetch(
    `${API_URL}/api/store/${encodeURIComponent(storeId)}/adopt`,
    { method: "POST", credentials: "include" },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    // 409 = house full / 403 = plan — the detail is the message to show.
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not adopt this pet");
  }
  return r.json();
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
  /** May this user give a pet to the store (SPEC_PET_STORE §10.1 gate 2)?
   *  True on every tier today — it exists so the lever is a data edit. */
  can_donate: boolean;
  upsell: string;
  base_design_cost: number | null;   // host base charge; null if unknown
}

export async function fetchEntitlement(): Promise<Entitlement> {
  // Credentialed: a launched user's tier rides their launch cookie.
  const r = await apiFetch(`${API_URL}/api/entitlement`, {
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

export interface MotionPoseControl {
  kind: string;          // "pose_prompt" | "pose_skeleton" | "depth"
  pose?: string;         // the pose_prompt clause (§3.9.1)
  ref?: string;
  strength?: number;
}
// SPEC_BUNDLE_MOTION_CONTRACT §3.3 — the view block ({view_kind, native_facing,
// mirroring_policy}); profile-level default + optional per-pose override.
export interface MotionViewSpec {
  view_kind: string;
  native_facing: string;
  mirroring_policy: string;
}
export interface MotionPoseSpec {
  enabled: boolean;
  runtime_role?: string | null;
  action?: string | null;
  suffix?: string;
  control?: MotionPoseControl | null;
  loop?: boolean;                    // §3.1 — a `triggered` pose is one-shot (false)
  timed_buffer_ms?: number | null;   // §3.2 — host `timed` dwell; only when authored
  view?: MotionViewSpec | null;      // §3.3 — per-pose view override
}
export interface MotionProfileFile {
  key: string;
  level: number;
  movement_class: string;
  keywords: string[];
  poses: Record<string, MotionPoseSpec>;
  view?: MotionViewSpec;   // §3.3 — required at write time; optional here for round-trip
  base_pose?: string;      // the posture the shared base still is drawn in (default "standing");
                           // aquatic bodies set "swimming, body horizontal" so fish aren't upright
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
// Every piece of text a generation sends, served from the Python constants
// (pet_factory/prompt_templates.py + motion_profiles) so the editor's prompt preview can
// never drift from what generation actually sends. Placeholders are `{animal}` / `{pose}`
// (still) and `{animal}` / `{action}` / `{suffix}` (motion). No negative prompts: the
// samplers run at cfg 1.0, which cancels negative conditioning out (see factory.py).
export interface MotionPromptTemplates {
  still: { base: string; remix: string; default_pose: string };
  motion: { template: string };
}
// What a real BUILD would resolve an animal to, and which resolver decided it. The Lab
// auto-matches by keyword (instant, free); this is the build's own AI-first answer, so
// the Lab can flag a disagreement instead of previewing the wrong body silently.
export interface MotionClassification {
  animal: string;
  profile_key: string;
  source: "ai" | "keyword";
}
export interface MotionProfileDetail {
  profile: MotionProfileFile;
  label: string;
  is_default: boolean;
  pinned_by: string[];
  writable: boolean;
}

// Thrown by every content-admin call (motions + design); carries the server's
// validation error list on a 422.
export class AdminApiError extends Error {
  status: number;
  errors: string[];
  constructor(message: string, status: number, errors: string[] = []) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

async function adminApiFetch(base: string, path: string, init?: RequestInit) {
  const r = await apiFetch(`${API_URL}${base}${path}`, {
    credentials: "include",
    cache: "no-store",
    // FormData must set its OWN Content-Type: the multipart boundary is generated by the
    // browser, and forcing application/json here makes the server read the parts as a JSON
    // body and reject the upload.
    headers: init?.body && !(init.body instanceof FormData)
      ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (r.ok) return r.json().catch(() => ({}));
  const data = await r.json().catch(() => ({}));
  // 422 detail = {error, errors[]}; other errors carry a string/detail.
  const detail = data.detail;
  const errors = detail && typeof detail === "object" ? detail.errors ?? [] : [];
  const msg = detail && typeof detail === "object" ? (detail.error ?? "request failed")
    : (detail ?? "request failed");
  throw new AdminApiError(String(msg), r.status, errors);
}

const motionFetch = (path: string, init?: RequestInit) =>
  adminApiFetch("/api/admin/motions", path, init);

export const motionAdmin = {
  list: (): Promise<MotionAdminList> => motionFetch(""),
  get: (key: string): Promise<MotionProfileDetail> => motionFetch(`/${encodeURIComponent(key)}`),
  promptTemplates: (): Promise<MotionPromptTemplates> => motionFetch("/prompt-templates"),
  classify: (animal: string): Promise<MotionClassification> =>
    motionFetch(`/classify?animal=${encodeURIComponent(animal)}`),
  create: (profile: MotionProfileFile, label: string) =>
    motionFetch("", { method: "POST", body: JSON.stringify({ profile, label }) }),
  update: (key: string, profile: MotionProfileFile, label: string) =>
    motionFetch(`/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ profile, label }) }),
  remove: (key: string) =>
    motionFetch(`/${encodeURIComponent(key)}`, { method: "DELETE" }),
  duplicate: (key: string, new_key: string, new_label: string): Promise<{ profile: MotionProfileFile }> =>
    motionFetch(`/${encodeURIComponent(key)}/duplicate`, { method: "POST", body: JSON.stringify({ new_key, new_label }) }),
};

// ---------------------------------------------------------------------------
// The Motion Lab (SPEC_MOTION_LAB) — the pose_prompt authoring workbench. These
// endpoints run the generation STEPS (a still, a loop) and exist ONLY on the local
// GPU backend (they 404 on the prod tier). Save is the motionAdmin.update above.
// ---------------------------------------------------------------------------
export interface LabAsset { asset_id: string; url: string; ms: number }
// Generation is a JOB (it outlasts the dev proxy's connection timeout): start →
// poll /job/{id} → the page shows an elapsed timer and can /cancel.
// What the hole fill did to one packed pose (SPEC_MATTE_REPAIR_ORDER §1). Computed by
// `factory.matte_fill_damage` — the same function scripts/probe_matte_fill.py prints, so a
// Lab number and a probe number cannot disagree. `hard_zero_px` is the one that decides:
// opaque pure black is arithmetically impossible from a matte, so any non-zero count IS the
// defect. A high `filled_pct` alone is not damage — the otter bundle was 23% filled and shipped clean.
export interface LabMatteMetrics {
  hard_zero_px: number;
  filled_pct: number;
  glaring_pct: number;
  line: string;           // the preformatted readout, so the tile and the probe say it identically
}
export interface LabJob {
  state: "running" | "done" | "error" | "canceled";
  // "packing" is F4's stage (§12.2): the loop is already published and served while the
  // packer runs, so a client can render the raw tile before the packed one exists.
  phase: "pending" | "running" | "packing";
  asset_id: string | null;
  url: string | null;
  ms: number | null;
  error: string | null;
  elapsed: number;
  // F4's second result slot. All null on `pack: false` or before the pack lands.
  packed_asset_id: string | null;
  packed_url: string | null;           // the packed SHEET, for PosePlayer
  packed_manifest_url: string | null;  // …and its manifest, which is where fps/frames live
  packed_zip_url: string | null;  // the real bundle — feed it to scripts/probe_matte_fill.py
  metrics: LabMatteMetrics | null;
  // A packer failure, NAMED — deliberately not `error`, because a job whose pack failed
  // still produced a ~40 s loop and "which stage broke" must be readable off the record.
  pack_error: string | null;
}
// Step 2's structured design, as the Lab sends it (SPEC_MOTION_LAB_DESIGN_PARITY §2.2).
// The SERVER composes it — `prompt_fragment` never reaches the browser, so a browser-side
// composer would be a second implementation of ordering rules still under calibration.
export interface LabDesign {
  color?: string;
  accessories?: string[];
  axis_picks?: Record<string, string>;
  extra?: string;
}
export interface LabStillOptions {
  /** The still to redraw FROM. Decides img2img vs txt2img — never the prompt template (§2.6). */
  reference_id?: string;
  /** The shared base still, as opposed to a pose anchor. EVERY base draw sets it (§2.6). */
  base?: boolean;
  strength?: number;
  /** Spent on a base redraw of a reference and nowhere else — the server 400s otherwise (I13). */
  design?: LabDesign;
}
// What the draw spent, and what it leaves behind — all known at request time, so they ride
// the START response rather than the job record (I5). LabJob stays a job-status shape.
export interface LabStillStarted {
  job_id: string;
  /** The exact string spent on THIS draw: the composed design, or the subject if undesigned. */
  description: string;
  /** The subject a build would now carry into step 3 — "white snow leopard". See poseSubject. */
  subject: string;
  /** The denoise floor the design forced, so the strength control can say so. */
  min_strength: number | null;
}
const labFetch = (path: string, init?: RequestInit) =>
  adminApiFetch("/api/admin/motion-lab", path, init);
export const motionLab = {
  // clause "" → the standing base; a clause → the pose anchor (§3.9.1). Build the opts with
  // `baseDrawOptions` (labDraw.ts) rather than by hand — `base` selects the prompt SENTENCE.
  startStill: (animal: string, clause: string, seed?: number,
               opts?: LabStillOptions): Promise<LabStillStarted> => {
    const { design, ...draw } = opts ?? {};
    // The design fields are flat on the wire (one StillBody), grouped in the client so a
    // caller cannot half-send one.
    return labFetch("/still", { method: "POST", body: JSON.stringify({ animal, clause, seed, ...draw, ...design }) });
  },
  // Upload a photo into the Lab. Runs the REAL upload door's triage + captioner, so that
  // path is exercised here rather than only in a 3-minute designer build.
  uploadReference: (file: File): Promise<LabReference> => {
    const fd = new FormData();
    fd.append("image", file);
    return labFetch("/reference", { method: "POST", body: fd });
  },
  // Runs the Wan loop AND then the shipped packer, as one job (F4). `pack: false` is the
  // bisection lever — the loop alone, skipping the eviction tax on a batch.
  startAnimate: (asset_id: string, animal: string, profile_key: string, pose_name: string,
                 seed?: number, pack = true): Promise<{ job_id: string }> =>
    labFetch("/animate", { method: "POST", body: JSON.stringify({ asset_id, animal, profile_key, pose_name, seed, pack }) }),
  job: (job_id: string): Promise<LabJob> => labFetch(`/job/${encodeURIComponent(job_id)}`),
  cancel: (job_id: string): Promise<unknown> => labFetch(`/cancel/${encodeURIComponent(job_id)}`, { method: "POST" }),
  config: (): Promise<{ endpoints: LabEndpoint[] }> => labFetch("/config"),
  setConfig: (active: number[]): Promise<unknown> => labFetch("/config", { method: "PUT", body: JSON.stringify({ active }) }),
  // AI draft of a pose clause (optional; 503s if DATSPET_AI_API_KEY is unset — SPEC_MOTION_LAB §2).
  suggestClause: (animal: string, pose: string, movement_class: string): Promise<{ clause: string }> =>
    labFetch("/suggest-clause", { method: "POST", body: JSON.stringify({ animal, pose, movement_class }) }),
  // The asset endpoint carries the adm cookie (same-origin <img> sends credentials).
  assetUrl: (url: string): string => `${API_URL}${url}`,
};
// A photo uploaded into the Lab, as the real upload door's captioner read it.
// `usable: false` means triage REJECTED the photo — surfaced, not swallowed, because that
// rejection is exactly the failure that drew a dog from a photograph of a person.
export interface LabReference {
  reference_id: string;
  url: string;
  usable: boolean;
  subject: string;
  features: string;
  description: string;
}
// A ComfyUI endpoint (one GPU). The Lab dispatches jobs across the active+healthy ones.
export interface LabEndpoint { index: number; label: string; url: string; healthy: boolean; active: boolean; inflight: number }

// ---------------------------------------------------------------------------
// Design admin (SPEC_PET_DESIGN_AXES_ADMIN §2) — the motion admin, applied to
// design: the axis vocabulary (Features) + per-animal profiles (Animals). This
// gated surface is the one place fragments DO reach the browser: editing the
// calibrated wording is its job.
// ---------------------------------------------------------------------------
export interface DesignAxisOptionFile {
  key: string;
  label: string;
  prompt_fragment: string;
}
export interface DesignAxisFile {
  _doc?: string;
  axis: string;
  label: string;
  kind: "universal" | "surface";
  applies_to?: string;
  default: string;
  clause_slot: number;
  position: "prefix" | "suffix";
  min_strength: number | null;
  options: DesignAxisOptionFile[];
}
export interface DesignAxisSummary {
  key: string;
  label: string;
  kind: "universal" | "surface";
  applies_to: string | null;
  default: string;
  option_count: number;
  clause_slot: number | null;
  position: string | null;
  min_strength: number | null;
  used_by: string[];
}
export interface DesignAdminAxisList {
  writable: boolean;
  max_concurrent_strong: number | null;
  axes: DesignAxisSummary[];
}
export interface DesignAxisDetail {
  axis: DesignAxisFile;
  used_by: string[];
  writable: boolean;
}
export interface DesignProfileFields {
  surface: string | null;
  surface_default: string | null;
  surface_options: string[] | null;
}
export interface DesignBreedProfile extends DesignProfileFields {
  key: string;
  label: string;
  resolved_surface: string | null;
}
export interface DesignAnimalProfile extends DesignProfileFields {
  key: string;
  label: string;
  breeds: DesignBreedProfile[];
}
export interface DesignAdminAnimals {
  writable: boolean;
  surfaces: string[];
  surface_axis_options: Record<string, DesignAxisOption[]>;
  animals: DesignAnimalProfile[];
}

// Calibration freshness (SPEC_PET_DESIGN_AXES_CALIBRATION §6) — per-cell
// verdicts so the Features tab can badge options that need recalibrating. Read
// -only; the render/heal loop is a dev-box command, never a browser action.
export interface DesignCalibrationCell {
  animal: string;
  cell: string;
  axis: string | null;
  option: string | null;
  verdict: "current" | "missing" | "stale";
  reason: string;
}
export interface DesignCalibrationStatus {
  available: boolean;
  reason?: string;
  reviewed: { at: string; notes: string } | null;
  unreviewed_render_count: number;
  substrate_mismatch?: string[];
  orphans?: { animal: string; cell: string }[];
  cells: DesignCalibrationCell[];
}

const designFetch = (path: string, init?: RequestInit) =>
  adminApiFetch("/api/admin/design", path, init);

export const designAdmin = {
  listAxes: (): Promise<DesignAdminAxisList> => designFetch("/axes"),
  calibrationStatus: (): Promise<DesignCalibrationStatus> => designFetch("/calibration-status"),
  getAxis: (key: string): Promise<DesignAxisDetail> => designFetch(`/axes/${encodeURIComponent(key)}`),
  createAxis: (axis: DesignAxisFile) =>
    designFetch("/axes", { method: "POST", body: JSON.stringify({ axis }) }),
  updateAxis: (key: string, axis: DesignAxisFile) =>
    designFetch(`/axes/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ axis }) }),
  removeAxis: (key: string) =>
    designFetch(`/axes/${encodeURIComponent(key)}`, { method: "DELETE" }),
  animals: (): Promise<DesignAdminAnimals> => designFetch("/animals"),
  setProfile: (animal: string, breed: string | null, profile: Partial<DesignProfileFields>) =>
    designFetch(
      breed
        ? `/animals/${encodeURIComponent(animal)}/${encodeURIComponent(breed)}`
        : `/animals/${encodeURIComponent(animal)}`,
      { method: "PUT", body: JSON.stringify(profile) },
    ),
};

// ---------------------------------------------------------------------------
// AI engine admin (SPEC_DATSPET_AI_ENGINE §6) — the third admin surface: the
// editable purpose registry, the READ-ONLY model catalog, usage (est. cost
// derived server-side from the catalog), and a Test-configuration probe. Gated
// like the others; inert until DATSPET_AI_API_KEY is set.
// ---------------------------------------------------------------------------
export interface AiModelEntry {
  id: string;
  label: string;
  provider: string;
  tier: string;
  status: string;
  vision: boolean;
  cost_per_mtok: { input: number; output: number };
  default_for_tiers: string[];
  replacement_id?: string;
}
export interface AiPurposeSummary {
  purpose_key: string;
  display_name: string;
  description: string;
  tier: string;
  max_tokens: number;
  input: string;
  is_active: boolean;
}
export interface AiPurposeFile {
  _doc?: string;
  purpose_key: string;
  display_name: string;
  description: string;
  tier: string;
  max_tokens: number;
  input: "text" | "image";
  template_vars: string[];
  system_prompt: string;
  user_prompt_template: string;
  output_schema: Record<string, unknown>;
  is_active: boolean;
}
export interface AiAdminStatus {
  available: boolean;
  writable: boolean;
  purpose_count: number;
  model_count: number;
}
export interface AiPurposeList {
  writable: boolean;
  available: boolean;
  tiers: string[];
  purposes: AiPurposeSummary[];
}
export interface AiPurposeDetail {
  purpose: AiPurposeFile;
  tiers: string[];
  writable: boolean;
}
export interface AiUsagePurpose {
  purpose_key: string;
  calls: number;
  ok_calls: number;
  error_calls: number;
  input_tokens: number;
  output_tokens: number;
  est_cost_usd: number;
  models: string[];
}
export interface AiUsageReport {
  days: number;
  total_cost_usd: number;
  purposes: AiUsagePurpose[];
}
export interface AiTestResult {
  ok: boolean;
  kind?: "unavailable" | "error";
  reason?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  est_cost_usd?: number;
  result?: unknown;
}

const aiFetch = (path: string, init?: RequestInit) =>
  adminApiFetch("/api/admin/ai", path, init);

export const aiAdmin = {
  status: (): Promise<AiAdminStatus> => aiFetch("/status"),
  listPurposes: (): Promise<AiPurposeList> => aiFetch("/purposes"),
  getPurpose: (key: string): Promise<AiPurposeDetail> => aiFetch(`/purposes/${encodeURIComponent(key)}`),
  updatePurpose: (key: string, purpose: AiPurposeFile) =>
    aiFetch(`/purposes/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ purpose }) }),
  models: (): Promise<{ models: AiModelEntry[] }> => aiFetch("/models"),
  usage: (days = 30): Promise<AiUsageReport> => aiFetch(`/usage?days=${days}`),
  test: (): Promise<AiTestResult> => aiFetch("/test", { method: "POST" }),
};

// ── Settings admin (SPEC_UPLOAD_LIKENESS §2.2, decision 6a) ──────────────────
// The runtime feature-flag switchboard — one adapter, every flag typed the same.
export interface AppSetting {
  key: string;
  type: "bool";
  label: string;
  description: string;
  value: boolean;
  default: boolean;
}

const settingsFetch = (path: string, init?: RequestInit) =>
  adminApiFetch("/api/admin/settings", path, init);

export const settingsAdmin = {
  list: (): Promise<{ settings: AppSetting[] }> => settingsFetch(""),
  set: (key: string, value: boolean): Promise<{ updated: AppSetting }> =>
    settingsFetch(`/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify({ value }) }),
};

// ── Store admin (SPEC_PET_STORE §3.2) — the sixth admin surface ──────────────
//
// DB-backed and runtime-writable everywhere (no writability gate): stocking
// prod must not require a deploy. The stocking door is intakeFromPet — the
// admin designs a pet in the NORMAL designer, then copies it onto the shelf.

/** The shelf lifecycle (SPEC_PET_STORE §1.4). Only `shelf` is visible to
 *  shoppers; the other three are three different reasons a pet is not for
 *  sale, which is exactly what the boolean this replaced could not say. */
export const STORE_STATUSES = ["intake", "shelf", "backroom", "archived"] as const;
export type StoreStatus = (typeof STORE_STATUSES)[number];

/** How each state reads to an admin. `intake` leads because a newest-first
 *  table makes it the inbox. */
export const STORE_STATUS_LABEL: Record<StoreStatus, string> = {
  intake: "Intake — not looked at yet",
  shelf: "On the shelf — for sale",
  backroom: "Backroom — kept, not for sale",
  archived: "Archived — not for sale, kept as a record",
};

/** The same four states as one word each, for the per-row triage select where
 *  the full sentence would not fit and is not needed — the row itself is the
 *  context the sentence was supplying. */
export const STORE_STATUS_SHORT: Record<StoreStatus, string> = {
  intake: "Intake",
  shelf: "Shelf",
  backroom: "Backroom",
  archived: "Archived",
};

/** The admin's slice of a store pet: the listing plus shelf state and the
 *  live sellability verdict (§5.3). */
export interface StoreAdminListing extends StoreListing {
  status: StoreStatus;
  admin_note: string;
  /** Stamped by the server on the FIRST shelving, never cleared. Read-only:
   *  it is what freezes `animal` for good (§1.3). */
  first_shelved_at: number | null;
  /** Who gave this listing to the store, when it arrived as a donation
   *  (§10.4). A READ-TIME join from the donation ledger — never a column on
   *  store_pets, because the engine must not be able to ask where a listing
   *  came from (§1.2). Null for anything an admin stocked herself. */
  donated_by?: string | null;
  sellability_errors?: string[];
}

export interface StoreDraftResult {
  listing: StoreAdminListing;
  // The AI's name idea — a SUGGESTION the editor shows, never auto-applied (§5.1).
  display_name_suggestion: string | null;
}

const storeFetch = (path: string, init?: RequestInit) =>
  adminApiFetch("/api/admin/store", path, init);

export const storeAdmin = {
  list: (): Promise<{ pets: StoreAdminListing[] }> => storeFetch(""),
  /** The card portrait as the ADMIN may see it — every shelf state, not just
   *  `shelf`. `storePreviewUrl` is the shopper's, and it 404s anything off the
   *  shelf (§1.4), which is most of this surface. */
  previewUrl: (id: string): string =>
    `${API_URL}/api/admin/store/${encodeURIComponent(id)}/preview.png`,
  get: (id: string): Promise<StoreAdminListing> =>
    storeFetch(`/${encodeURIComponent(id)}`),
  /** MOVE a house pet into store inventory (§5.1) — the pet leaves the house,
   *  exactly as a donation does. Not a copy: a house duplicate cannot be sold,
   *  holds a slot, and invites stocking the same pet twice. */
  intakeFromPet: (petId: string): Promise<StoreDraftResult> =>
    storeFetch("/intake-from-pet", {
      method: "POST", body: JSON.stringify({ pet_id: petId }),
    }),
  /** The AUTHORED fields only. Shelf state moves through `setStatus`. */
  update: (id: string, body: {
    display_name: string; description: string; tags: string[];
    animal: string; admin_note: string;
  }): Promise<{ listing: StoreAdminListing }> =>
    storeFetch(`/${encodeURIComponent(id)}`, {
      method: "PUT", body: JSON.stringify(body),
    }),
  /** One shelf move (§1.4). The payload is the destination and nothing else,
   *  so it needs no prior read and cannot clobber text someone is editing. */
  setStatus: (id: string, status: StoreStatus, adminNote?: string):
    Promise<{ listing: StoreAdminListing }> =>
    storeFetch(`/${encodeURIComponent(id)}/status`, {
      method: "POST",
      body: JSON.stringify(adminNote === undefined
        ? { status } : { status, admin_note: adminNote }),
    }),
  /** Write description + tags with AI (SPEC_PET_STORE §4). Overwrites both,
   *  so the caller confirms first — the host's AI-tag door works the same way. */
  aiTag: (id: string): Promise<StoreDraftResult> =>
    storeFetch(`/${encodeURIComponent(id)}/ai-tag`, { method: "POST" }),
  remove: (id: string): Promise<{ deleted: string }> =>
    storeFetch(`/${encodeURIComponent(id)}`, { method: "DELETE" }),
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
  // The AI's guess at the subject (animal or person) for an upload
  // (SPEC_UPLOAD_LIKENESS §2.5), or null. The upload door prefills its noun field with
  // this on an empty submit; the human's typed word wins, so it is null-or-ignored
  // whenever the user named the subject themselves.
  suggested_subject: string | null;
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
  const r = await apiFetch(`${API_URL}${path}`, {
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

// The design-step vocabulary, filtered server-side by the resolved surface
// (SPEC_PET_DESIGN_AXES §4). Two ways to name the animal, and the server prefers
// `referenceId` when both are given — never merges them:
//   referenceId  the designer, which always holds a reference by step 2
//   animal       the Motion Lab, which has free text and no reference (§2.1)
// Neither → the universal axes: a menu endpoint must not dead-end the step.
//
// An OPTIONS OBJECT, not two optional positional strings (I8): `fetchDesignAxes(animal)`
// would type-check, be read as a reference id, fail to load, and degrade silently to the
// universal axes — the call that looks most obviously right breaking in the one way this
// endpoint is designed never to complain about. Credentialed: references are owner-scoped.
export async function fetchDesignAxes(
  opts: { referenceId?: string; animal?: string } = {},
): Promise<{ axes: DesignAxis[] }> {
  const params = new URLSearchParams();
  if (opts.referenceId) params.set("reference_id", opts.referenceId);
  else if (opts.animal) params.set("animal", opts.animal);
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`${API_URL}/api/design-axes${qs}`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!r.ok) throw new Error("Could not load design options");
  return r.json();
}

export async function keepPet(petId: string): Promise<void> {
  const r = await apiFetch(`${API_URL}/api/pets/${encodeURIComponent(petId)}/keep`, {
    method: "POST",
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Could not save the pet");
  }
}

export async function renamePet(
  petId: string, name: string,
): Promise<{ id: string; pet_name: string | null }> {
  const r = await apiFetch(`${API_URL}/api/pets/${encodeURIComponent(petId)}/name`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Could not rename the pet");
  }
  return r.json();
}

export async function deletePet(petId: string): Promise<void> {
  const r = await apiFetch(`${API_URL}/api/pets/${encodeURIComponent(petId)}`, {
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
  // The launch cookie is present but its token no longer verifies — the user is
  // still signed in on DatsMe, we just need a fresh assertion. Drives the silent
  // re-launch (SPEC_DATSPET_FEDERATED_SESSION §4.2). Distinct from
  // `launched:false` with no cookie, which means genuinely signed out.
  stale?: boolean;
  user_id?: string;
  display_name?: string | null;  // the signed-in user's DatsMe name (nm claim), for the nav
  capabilities?: string[];
  /** Has this user allowed DatsMe to thank her with social points when she
   *  donates a pet (SPEC_PET_STORE §10.8)? A UI HINT only — the host is the
   *  enforcement point. When false the donate door asks for the grant instead
   *  of taking a pet and silently failing to pay for it. */
  can_be_thanked?: boolean;
  cost?: number | null;
  // Front-door fields (SPEC_DATSPET_FRONT_DOOR §3.2). Present on every response.
  integrated?: boolean;         // wired to a DatsMe host? false = standalone (no DatsMe buttons)
  signin_url?: string | null;   // where "Sign in with DatsMe" points (host login-launch bounce)
  signup_url?: string | null;   // where "Create a DatsMe account" points (host /signup)
  // Where the donate door sends someone who has not granted `social.award`.
  // Built server-side like the rest — the browser never assembles a DatsMe origin.
  consent_url?: string | null;
  // Where "Sign out" NAVIGATES (never fetches — see datsmeSignOut). Built
  // server-side like the others; the browser never assembles a DatsMe origin.
  signout_url?: string | null;
  // Where the Adopt hand-off goes: `${import_url}?items=a,b,c`. Built server-side —
  // the partner slug is env-overridable, so the browser must never assemble this
  // itself (SPEC_DATSPET_HOUSE_ADOPT §0.6).
  import_url?: string | null;
  // Seconds until the launch assertion lapses, so the client can renew BEFORE it
  // does rather than after (§4.2).
  token_expires_in?: number | null;
  admin?: boolean;              // a valid admin session is present (show the admin tools)
  // Would this user PASS the admin bounce? A display hint only — `admin` above is
  // the real grant. This decides whether the nav offers the Admin entry point at
  // all, so a non-admin is never invited to click something the host will bounce
  // straight back with ?signin=admin_denied.
  system_admin?: boolean;
}

export async function getDatsmeSession(): Promise<DatsmeSession> {
  // Raw fetch, deliberately NOT apiFetch: this is the one endpoint that never
  // 401s on a stale session — it reports `stale: true` instead, because it is what
  // TELLS the client to renew (§4.7). Routing it through the wrapper would make
  // the renewal path re-enter itself.
  //
  // credentials: the launch cookie is httponly, so it must ride cross-origin.
  const r = await fetch(`${API_URL}/api/datsme/session`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!r.ok) return { launched: false };
  return r.json();
}

// ---------------------------------------------------------------------------
// Sign out, and staying signed in (SPEC_DATSPET_FEDERATED_SESSION §4.2 / §5.1)
// ---------------------------------------------------------------------------

// Marks a page load that ARRIVED from a renewal attempt. The loop guard: if we
// land carrying it and the session still is not live, the host declined (revoked
// consent, a tripped health gate) and renewing again would loop forever. One
// query flag, no cookie and no TTL to tune — and the host's own return-path
// validator already admits `?` and `=`, so it survives the round trip.
const RENEWED_MARKER = "renewed";

// Renew when the assertion has less than this left. Comfortably longer than any
// single page interaction, far shorter than the 60-minute window, so a normal
// visit renews at most once.
export const LAUNCH_RENEW_THRESHOLD_SEC = 15 * 60;

/** Sign out of BOTH DatsPet and DatsMe. A NAVIGATION, never a fetch.
 *
 * A fetch cannot clear a cookie on another origin, and the DatsMe session cookie
 * is SameSite=Lax, so it would not even be sent. The browser has to actually go
 * there. This is the whole reason one user could not hand the browser to another:
 * the old POST cleared DatsPet's cookies and left the DatsMe session alive, so the
 * next "Sign in" silently re-minted the same person.
 */
export function datsmeSignOut(session: DatsmeSession | null): void {
  // signout_url is null in standalone mode and when there is no launch cookie;
  // the backend endpoint handles both and lands on our own page.
  window.location.href = session?.signout_url || `${API_URL}/api/datsme/signout`;
}

/** The URL that silently re-launches, returning to `returnPath`. */
/** Exported for test: the pure half of the sign-in URL rule. `datsmeSignInUrlForHere`
 *  is the same thing plus a `window` read, which is the part that cannot be tested
 *  here (vitest is deliberately DOM-free — see vitest.config.ts). */
export function signinUrlReturningTo(session: DatsmeSession, returnPath: string): string | null {
  if (!session.signin_url) return null;
  const url = new URL(session.signin_url);
  // REPLACE rather than append: signin_url is prebuilt with return=/design, and a
  // second `return` parameter would be ambiguous. Reading the origin off the
  // server-supplied string is what keeps the DatsMe origin out of this file.
  url.searchParams.set("return", returnPath);
  return url.toString();
}

/** The URL that silently re-launches, returning to `returnPath`. */
export function datsmeRenewUrl(session: DatsmeSession, returnPath: string): string | null {
  const sep = returnPath.includes("?") ? "&" : "?";
  return signinUrlReturningTo(session, `${returnPath}${sep}${RENEWED_MARKER}=1`);
}

/** Sign in and come back to exactly HERE — path, query and all.
 *
 * The prebuilt `signin_url` always returns to /design, which is right from the
 * landing page and wrong from anywhere else. It is especially wrong mid-build: the
 * designer keeps its running job in `?job=<id>` (see usePetJob), so dropping the
 * query is what turned "design a pet, then sign in to adopt it" into a lost pet.
 * Sign-in is the ONE navigation a user makes expecting to end up where they were.
 */
export function datsmeSignInUrlForHere(session: DatsmeSession): string | null {
  if (typeof window === "undefined") return session.signin_url ?? null;
  return signinUrlReturningTo(session, currentReturnPath()) ?? session.signin_url ?? null;
}

/** Where "come back here" means, right now: path AND query.
 *
 * The query is not decoration — the designer keeps its running build in `?job=`,
 * so a return path built from `pathname` alone silently drops a 3-minute pet.
 * Read it at the moment of the navigation, NEVER captured earlier: the job id is
 * written with history.replaceState, which does not re-render React, so anything
 * computed at render time is stale by the time the user clicks.
 */
function currentReturnPath(): string {
  if (typeof window === "undefined") return "/";
  return window.location.pathname + window.location.search;
}

/** True if this page load already came back from a renewal attempt. */
export function arrivedFromRenewal(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has(RENEWED_MARKER);
}

/** Renew now if the assertion is close to lapsing. Returns true if navigating.
 *
 * Called on page load. Safe to call unconditionally: it is a no-op when there is
 * nothing to renew, when the assertion has plenty of time left, or when this load
 * already came back from a renewal that did not take.
 */
export function maybeRenewLaunch(session: DatsmeSession | null): boolean {
  if (!session?.launched || arrivedFromRenewal()) return false;
  const left = session.token_expires_in;
  if (typeof left !== "number" || left > LAUNCH_RENEW_THRESHOLD_SEC) return false;
  const url = datsmeRenewUrl(session, currentReturnPath());
  if (!url) return false;
  window.location.href = url;
  return true;
}

// The server's structured code for "your launch assertion lapsed" (§4.7). A code,
// never a message match: a client that string-matches an error breaks the moment
// the copy is edited.
const SESSION_STALE_CODE = "session_stale";

/** Turn a 401 session_stale into a silent re-launch — the ONE place that reacts.
 *
 * Every API helper funnels its failures through here, so the renewal decision and
 * its loop guard live in one place. Without that, each call site grows its own
 * copy and the guard gets forgotten in exactly one of them, which is how a
 * redirect loop ships.
 *
 * Returns true if it is navigating away (the caller should stop).
 */
export function handleSessionStale(status: number, body: unknown): boolean {
  if (status !== 401 || typeof window === "undefined") return false;
  const detail = (body as { detail?: { code?: string } } | undefined)?.detail;
  if (detail?.code !== SESSION_STALE_CODE || arrivedFromRenewal()) return false;
  // The session read is cheap and cannot itself be stale (it never 401s), so this
  // resolves the renew URL without keeping a session copy in module state.
  void getDatsmeSession().then((session) => {
    const url = datsmeRenewUrl(session, currentReturnPath());
    if (url) window.location.href = url;
  });
  return true;
}

/** Claim + keep + hand off to the host's checkout — the ONE purchase path.
 *
 * Three surfaces need this (the house, the post-design Adopt, and the catalog
 * page in SPEC_DATSPET_CATALOG_PURCHASE), and the order is the part that is easy
 * to get wrong, so it lives here once:
 *
 *   1. CLAIM. A pet designed before signing in is held under this browser's
 *      anonymous owner id, and /partner/export is exact-match on the DatsMe id —
 *      so an unclaimed pet is visible in the house yet invisible to the host, and
 *      would silently not appear on the checkout page. (Sign-in normally claims
 *      already; this is the backstop for a pet finished after that.)
 *   2. KEEP. The host skips drafts, so a pet that was never kept is not offered.
 *   3. NAVIGATE. The checkout is the host's page, authenticated by the user's own
 *      30-day DatsMe session — which is why token expiry can never cost a
 *      purchase any more.
 *
 * DECISION (cancel does NOT unclaim): a user who cancels on DatsMe has still
 * claimed and kept these pets. Claiming only binds ownership and charges nothing,
 * and the binding is what makes the pet correctly exportable on the next attempt;
 * unclaim-on-cancel would add a failure mode for zero user benefit.
 */
export async function handOffToDatsme(
  petIds: string[],
  session: DatsmeSession,
): Promise<void> {
  if (petIds.length === 0 || !session.import_url) return;
  await claimPets(petIds);
  await Promise.all(petIds.map((id) => keepPet(id)));
  window.location.href = `${session.import_url}?items=${petIds.join(",")}`;
}

// ── Donations (SPEC_PET_STORE §10) ──────────────────────────────────────────
//
// Donating is FINAL: the pet becomes store inventory at the click and the donor
// does not get it back (§0.5). She is thanked with a social point — awarded by
// DatsMe, which decides the amount and may decline (§10.7).

export type RewardState =
  | "owed" | "delivered" | "capped" | "disabled" | "declined";

export interface Donation {
  id: string;
  store_pet_id: string;
  display_name: string;
  donated_at: number;
  reward_state: RewardState;
  /** What the HOST said it gave. NULL until it has answered — never a number
   *  DatsPet computed or remembered from a knob it does not own (§10.8). */
  points_awarded: number | null;
}

export interface DonationResult {
  donation_id: string;
  display_name: string;
  thanks: string;
}

/** Give a pet to the store. Irreversible — the caller confirms first. */
export async function donatePet(petId: string): Promise<DonationResult> {
  const r = await apiFetch(
    `${API_URL}/api/pets/${encodeURIComponent(petId)}/donate`,
    { method: "POST" });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    const detail = data.detail;
    // The door refuses with a REASON (§10.1) — show it, because "could not
    // donate" tells a user nothing about which pet to try instead.
    const reasons = detail && Array.isArray(detail.errors) ? detail.errors : null;
    throw new Error(
      reasons ? reasons.join("; ")
        : (typeof detail === "string" ? detail : "Could not donate that pet"));
  }
  return r.json();
}

export async function listMyDonations(): Promise<Donation[]> {
  const r = await apiFetch(`${API_URL}/api/donations`);
  if (!r.ok) return [];
  const data = await r.json().catch(() => ({ donations: [] }));
  return data.donations ?? [];
}

// ---------------------------------------------------------------------------
// Arena rooms (SPEC_PET_ARENA_ROOMS §4.2) — live multi-device racing. Every
// room URL is minted HERE, the one-adapter rule; the transport client in
// web/src/arena/room/ owns lifecycle (EventSource, reconnection), never URLs.
// ---------------------------------------------------------------------------

export interface ArenaRoomPlayer {
  pet_id: string;
  pet_label: string;
  handicap_name: string;
  is_host: boolean;
}

export interface ArenaRoomSnapshot {
  code: string;
  state: "lobby" | "countdown" | "racing" | "finished";
  event_key: string;
  challenge_key: string;
  difficulty: string;
  question_seed: number;
  max_players: number;
  countdown_ends_at: number | null;
  standings: ArenaTickPosition[] | null;
  server_now: number;
  players: ArenaRoomPlayer[];
}

export interface ArenaRoomEntrant {
  pet_id: string;
  pet_label: string;
  handicap_name: string;
}

async function arenaRoomPost(path: string, body: unknown): Promise<any> {
  const r = await apiFetch(`${API_URL}/api/arena/rooms${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "The room did not answer");
  }
  return r.json();
}

export async function createArenaRoom(setup: {
  event_key: string; challenge_key: string; difficulty: string;
  max_players?: number;
} & ArenaRoomEntrant): Promise<{ code: string; host_token: string; room: ArenaRoomSnapshot }> {
  return arenaRoomPost("", setup);
}

export async function joinArenaRoom(
  code: string, entrant: ArenaRoomEntrant,
): Promise<{ player_token: string; room: ArenaRoomSnapshot }> {
  return arenaRoomPost(`/${encodeURIComponent(code)}/join`, entrant);
}

export async function startArenaRoom(
  code: string, token: string,
): Promise<{ room: ArenaRoomSnapshot }> {
  return arenaRoomPost(`/${encodeURIComponent(code)}/start`, { token });
}

export function arenaRoomStreamUrl(code: string): string {
  return `${API_URL}/api/arena/rooms/${encodeURIComponent(code)}/stream`;
}

/** The pair every racer loader consumes (F16): the loader never decides
 *  WHERE assets come from — the caller mints the pair here, so a new asset
 *  source (a lounge, a replay) is a new minting helper, never a loader
 *  branch. */
export interface PetAssetUrls {
  manifestUrl: string;
  sheetUrl: string;
}

/** The owner-scoped pair — my own pets. */
export function petAssetUrls(petId: string): PetAssetUrls {
  return { manifestUrl: petManifestUrl(petId), sheetUrl: petSheetUrl(petId) };
}

/** Room-scoped pet assets (§4.3): membership in a live room is the
 *  capability — these serve any pet ENTERED in the room to anyone holding
 *  the code, and die with the room. Sheet + manifest only, never the zip. */
export function roomPetAssetUrls(code: string, petId: string): PetAssetUrls {
  const base = `${API_URL}/api/arena/rooms/${encodeURIComponent(code)}/pets/${encodeURIComponent(petId)}`;
  return { manifestUrl: `${base}/manifest.json`, sheetUrl: `${base}/sheet.png` };
}

export interface ArenaTickPosition {
  lane: number;
  pet_id: string;
  pet_label: string;
  handicap_name: string;
  distance_m: number;
  finished: boolean;
  finish_ms: number | null;
  rate_flagged: boolean;
}

export async function postArenaImpulses(
  code: string, token: string, impulses: { at: number; quality: number }[],
): Promise<{ accepted: number; total: number }> {
  return arenaRoomPost(`/${encodeURIComponent(code)}/impulses`,
                       { token, impulses });
}

export async function getArenaRoom(code: string): Promise<ArenaRoomSnapshot> {
  const r = await apiFetch(
    `${API_URL}/api/arena/rooms/${encodeURIComponent(code)}`);
  if (!r.ok) throw new Error("no such room");
  return (await r.json()).room;
}

/** The shareable spectator URL (R3) — /arena/{code}, served by nginx in prod
 *  and a dev rewrite under `next dev`. Minted here like every URL. */
export function arenaWatchUrl(code: string): string {
  if (typeof window !== "undefined") {
    return `${window.location.origin}/arena/${encodeURIComponent(code)}`;
  }
  return `/arena/${encodeURIComponent(code)}`;
}

// ---------------------------------------------------------------------------
// Arena lounges (SPEC_PET_ARENA_LOUNGE) — the permanent front door. Signed-in
// DatsMe users only; the pet is the identity (§3.2), so nothing here ever
// carries a person's name. Accepting a challenge hands back an ordinary room
// seat — from there the room adapter above takes over.
// ---------------------------------------------------------------------------

export interface ArenaLoungeListEntry {
  id: string;
  label: string;
  emoji: string;
  present: number;
}

export interface ArenaLoungePresence {
  presence_id: string;
  pet_id: string;
  pet_label: string;
}

export interface ArenaLoungeChallenge {
  id: string;
  from_presence: string;
  to_presence: string;
  event_key: string;
  challenge_key: string;
  difficulty: string;
  accepted: boolean;
  expires_at: number;
}

export interface ArenaLoungeBoardEntry {
  room_code: string;
  event_key: string;
  state: string;
  pet_labels: string[];
}

export interface ArenaLoungeSnapshot {
  id: string;
  label: string;
  emoji: string;
  present: ArenaLoungePresence[];
  challenges: ArenaLoungeChallenge[];
  racing: ArenaLoungeBoardEntry[];
  server_now: number;
}

/** A seat in a minted race room — accept and claim both return one, shaped
 *  so the caller can drop straight into the room phase. */
export interface ArenaLoungeRoomSeat {
  code: string;
  player_token: string;
  my_lane: number;
  room: ArenaRoomSnapshot;
}

async function arenaLoungePost(path: string, body: unknown): Promise<any> {
  const r = await apiFetch(`${API_URL}/api/arena/lounges${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "The lounge did not answer");
  }
  return r.json();
}

export async function listArenaLounges(): Promise<ArenaLoungeListEntry[]> {
  const r = await apiFetch(`${API_URL}/api/arena/lounges`);
  if (!r.ok) return [];
  const data = await r.json().catch(() => ({ lounges: [] }));
  return data.lounges ?? [];
}

export async function enterArenaLounge(
  loungeId: string, pet: { pet_id: string; pet_label: string },
): Promise<{ presence_token: string; presence_id: string; lounge: ArenaLoungeSnapshot }> {
  return arenaLoungePost(`/${encodeURIComponent(loungeId)}/enter`, pet);
}

export async function heartbeatArenaLounge(
  loungeId: string, token: string,
): Promise<void> {
  await arenaLoungePost(`/${encodeURIComponent(loungeId)}/presence`, { token });
}

export async function leaveArenaLounge(
  loungeId: string, token: string,
): Promise<void> {
  await arenaLoungePost(`/${encodeURIComponent(loungeId)}/leave`, { token });
}

export function arenaLoungeStreamUrl(loungeId: string): string {
  return `${API_URL}/api/arena/lounges/${encodeURIComponent(loungeId)}/stream`;
}

export async function createLoungeChallenge(
  loungeId: string,
  card: { token: string; to: string; event_key: string;
          challenge_key: string; difficulty: string },
): Promise<{ challenge_id: string; lounge: ArenaLoungeSnapshot }> {
  return arenaLoungePost(`/${encodeURIComponent(loungeId)}/challenge`, card);
}

export async function acceptLoungeChallenge(
  loungeId: string, challengeId: string, token: string,
): Promise<ArenaLoungeRoomSeat> {
  return arenaLoungePost(
    `/${encodeURIComponent(loungeId)}/challenge/${encodeURIComponent(challengeId)}/accept`,
    { token });
}

export async function claimLoungeChallenge(
  loungeId: string, challengeId: string, token: string,
): Promise<ArenaLoungeRoomSeat> {
  return arenaLoungePost(
    `/${encodeURIComponent(loungeId)}/challenge/${encodeURIComponent(challengeId)}/claim`,
    { token });
}
