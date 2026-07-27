"use client";

/**
 * Motion Lab (SPEC_MOTION_LAB, incl. §12 Phase 2 — multi-pose authoring). Tune the
 * pose_prompt clauses (§3.9.1) for MULTIPLE poses at once, all drawn from ONE shared
 * base + seed, so cross-pose colour/style drift is visible before you save.
 *
 * One column per selected pose: clause · anchor still · animation · save. Generation
 * is ASYNC (start → poll /job), with a live elapsed timer and a Cancel button. Several
 * generations may be fired at once — they QUEUE on the serial GPU and read "pending…"
 * until they start. LOCAL backend only. Save is the existing motion_admin write.
 *
 * DESIGN PARITY (SPEC_MOTION_LAB_DESIGN_PARITY). The setup card mirrors a real build's
 * first two steps: Draw base is step 1 (txt2img from the typed name), Apply design is
 * step 2 (the designer's own <DesignStep>, redrawn img2img, composed server-side). The
 * composed string is spent THERE and nowhere else — every pose anchor below is txt2img
 * from the SUBJECT in the remix sentence, which is what a build draws (§0.3, §2.6). After
 * a design that subject is the display name ("white snow leopard"), because that is what
 * step 2 saves on its new reference and step 3 reads back: the colour rides into every
 * anchor, the body shape and accessories do not. Imitating that asymmetry exactly is the
 * parity — being more designed than a build would make the Lab lie in the investigation
 * it exists to serve, and being less designed makes it draw the wrong animal.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  motionAdmin, motionLab, getDatsmeSession, AdminApiError, CANONICAL_POSES, fetchMotions,
  fetchDesignAxes,
  type MotionAdminList, type MotionClassification, type MotionProfileDetail, type MotionProfileFile,
  type LabAsset, type LabJob, type LabEndpoint, type DesignAxis, type LabMatteMetrics,
} from "@/lib/api";
import PosePlayer from "@/components/PosePlayer";
import { MAX_ACCESSORIES } from "@/app/design/general/designFlow";
import { ProfileEditor, type Draft } from "../ProfileEditor";
import ModalOverlay from "@/components/ModalOverlay";
import ConfirmModal from "@/components/ConfirmModal";
import DesignStep from "@/components/DesignStep";
import { baseDrawOptions, packedTile, poseSubject, type LabSource } from "./labDraw";

const DEFAULT_SEED = 42;
// The app's own default design/redraw denoise — DesignStep's "balanced" rung and
// /api/preview's `strength` default are this same number.
const DEFAULT_DENOISE = 0.85;
// The band every redraw is held inside, mirrored from design_calibration's
// MIN_DENOISE/MAX_DENOISE. The SERVER is authoritative (it clamps whatever arrives);
// naming them here keeps the slider from offering a value that would be silently moved.
const MIN_DENOISE = 0.3;
const MAX_DENOISE = 0.9;
const DENOISE_STEP = 0.05;
const inputStyle = { background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" };
const labelCls = "mono mb-1 block text-xs tracking-wide";
type Phase = LabJob["phase"];

type Cell = {
  clause: string; still: LabAsset | null; loop: LabAsset | null;
  busy: "" | "draw" | "animate" | "save" | "suggest"; jobId: string | null; elapsed: number; phase: Phase;
  // F4's second result: the SAME animation, packed. `packed` points PosePlayer at the Lab's
  // own sheet+manifest (there is no saved pet behind a scratch bundle); `packError` names the
  // stage when the pack alone failed, which must cost the packed tile and nothing else.
  packed: { sheetUrl: string; manifestUrl: string } | null;
  packError: string; metrics: LabMatteMetrics | null;
};
type Cells = Record<string, Cell>;

const genErr = (e: unknown) => e instanceof AdminApiError ? e.message : "Generation failed — is ComfyUI up?";
const saveErr = (e: unknown) => e instanceof AdminApiError ? (e.errors[0] ?? e.message) : "Save failed.";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Polls to a terminal state and returns the WHOLE job, not just its asset: an animate
// carries a second result (the packed sheet, its metrics, or the stage that failed), and
// a poller that returned one asset could not express that. `onTick` sees every reading, so
// a caller can render the raw loop the moment it lands — the pack runs on for ~6 s after.
async function pollJob(jobId: string, onTick: (j: LabJob) => void): Promise<LabJob | null> {
  for (;;) {
    const j = await motionLab.job(jobId);
    onTick(j);
    if (j.state === "done") return j;
    if (j.state === "canceled") return null;
    if (j.state === "error") throw new AdminApiError(j.error ?? "generation failed", 500);
    await sleep(1500);
  }
}
const assetOf = (j: LabJob): LabAsset => ({ asset_id: j.asset_id ?? "", url: j.url ?? "", ms: j.ms ?? 0 });
// The packed sheet as PosePlayer wants it — resolved by labDraw so the "a failed pack
// costs the tile and nothing else" rule is testable without a DOM (I10).
const packedOf = (j: LabJob) => packedTile(j, motionLab.assetUrl);

function profileWithClauses(base: MotionProfileFile, clauses: Record<string, string>): MotionProfileFile {
  const p = structuredClone(base);
  for (const [name, raw] of Object.entries(clauses)) {
    const c = raw.trim();
    const pose = { ...p.poses[name] };
    if (c) pose.control = { kind: "pose_prompt", pose: c };
    else delete pose.control;
    p.poses[name] = pose;
  }
  return p;
}

// "pending…" while queued, else "Verbing… 12s"; the idle label otherwise.
const runLabel = (busy: boolean, phase: Phase, elapsed: number, verb: string, idle: string) =>
  !busy ? idle : phase === "pending" ? "pending…" : `${verb}… ${elapsed}s`;

export default function MotionLabPage() {
  const [gate, setGate] = useState<"checking" | "ok" | "denied">("checking");
  const [list, setList] = useState<MotionAdminList | null>(null);
  const [profileKey, setProfileKey] = useState("");
  const [detail, setDetail] = useState<MotionProfileDetail | null>(null);
  const [animal, setAnimal] = useState("robin");
  const [matchedProfileFor, setMatchedProfileFor] = useState("");   // the animal the profile was auto-matched from
  const [buildMatch, setBuildMatch] = useState<MotionClassification | null>(null);  // what a real build would resolve to
  // The still the BASE draw is redrawn from — an uploaded photo, or a design applied to
  // an earlier base (I12). Present → the base is img2img from it, exactly as a build with
  // a reference does. It has no say in the anchors: those are txt2img either way (§2.6).
  const [source, setSource] = useState<LabSource | null>(null);
  const [refBusy, setRefBusy] = useState(false);
  const [baseDenoise, setBaseDenoise] = useState(DEFAULT_DENOISE);   // base-only denoise
  // Step 2's design (§2.2–§2.4): the designer's OWN <DesignStep>, over the one composer
  // server-side. These picks are spent on exactly one draw — the base redraw — and never
  // reach an anchor or a loop (§0.3). `composed` is the string the server actually spent,
  // read back off the /still response so the operator can see it (§2.3).
  const [color, setColor] = useState("");
  const [accessories, setAccessories] = useState<string[]>([]);
  const [axisPicks, setAxisPicks] = useState<Record<string, string>>({});
  const [extra, setExtra] = useState("");
  const [designStrength, setDesignStrength] = useState(DEFAULT_DENOISE);
  const [axes, setAxes] = useState<DesignAxis[]>([]);
  const [minStrength, setMinStrength] = useState<number | null>(null);
  const [composed, setComposed] = useState("");
  const [designOpen, setDesignOpen] = useState(false);   // closed by default: poses are the Lab's job
  const [designBusy, setDesignBusy] = useState(false);
  const [designJob, setDesignJob] = useState<string | null>(null);
  const [designElapsed, setDesignElapsed] = useState(0);
  const [designPhase, setDesignPhase] = useState<Phase>("running");
  const [seed, setSeed] = useState(DEFAULT_SEED);
  const [base, setBase] = useState<LabAsset | null>(null);
  const [basePose, setBasePose] = useState("standing");   // the posture the base still is drawn in (profile.base_pose)
  const [baseKind, setBaseKind] = useState<"" | "suggest" | "save">("");   // base-pose card's suggest/save op
  const [baseBusy, setBaseBusy] = useState(false);
  const [baseJob, setBaseJob] = useState<string | null>(null);
  const [baseElapsed, setBaseElapsed] = useState(0);
  const [basePhase, setBasePhase] = useState<Phase>("running");
  const [cells, setCells] = useState<Cells>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [baseSelected, setBaseSelected] = useState(false);   // the "Base" pill — its card is closed by default
  const [busyAll, setBusyAll] = useState<"" | "draw" | "animate" | "save">("");
  const [endpoints, setEndpoints] = useState<LabEndpoint[]>([]);
  const [notice, setNotice] = useState("");
  const [err, setErr] = useState("");
  // Profile CRUD (surfaced from the Motions page for the selected profile).
  const [editDraft, setEditDraft] = useState<Draft | null>(null);
  const [editErrors, setEditErrors] = useState<string[]>([]);
  const [editBusy, setEditBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  // Save writes straight to the motion profile (overwriting the stored clause), so it is confirmed.
  const [confirmSave, setConfirmSave] = useState<{ kind: "one" | "all" | "base"; name?: string } | null>(null);

  const loadConfig = () => motionLab.config().then((c) => setEndpoints(c.endpoints)).catch(() => {});
  async function toggleGpu(index: number) {
    const active = endpoints.filter((e) => e.active).map((e) => e.index);
    const next = active.includes(index) ? active.filter((i) => i !== index) : [...active, index];
    if (!next.length) return;   // keep at least one GPU active
    await motionLab.setConfig(next).catch(() => {});
    await loadConfig();
  }

  useEffect(() => {
    motionAdmin.list().then((l) => {
      setList(l);
      setGate("ok");
      loadConfig();
      const first = l.profiles.find((p) => p.key === "avian") ?? l.profiles[0];
      if (first) setProfileKey(first.key);
    }).catch(async (e) => {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) { window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/motions/lab`; return; }
      }
      setGate("denied");
    });
  }, []);

  // Load a profile into the Lab: its detail, the pose menu, and the default selection.
  // resetBase=false on a same-profile reload (an Edit save) so the drawn base survives.
  const loadProfileDetail = useCallback((key: string, resetBase = true) => {
    motionAdmin.get(key).then((d) => {
      setDetail(d);
      const enabled = CANONICAL_POSES.filter((n) => d.profile.poses[n]?.enabled);
      const next: Cells = {};
      for (const n of enabled) next[n] = { clause: d.profile.poses[n].control?.pose ?? "", still: null, loop: null, busy: "", jobId: null, elapsed: 0, phase: "running", packed: null, packError: "", metrics: null };
      setCells(next);
      // Default-open: walk + idle only (the required active/rest pair). Base and the rest stay closed.
      const def = enabled.filter((n) => ["walk", "idle"].includes(n));
      setSelected(def.length ? def : enabled.slice(0, 2));
      setBasePose(d.profile.base_pose ?? "standing");
      if (resetBase) { setBase(null); setBaseSelected(false); }
    }).catch(() => setDetail(null));
  }, []);

  useEffect(() => {
    if (profileKey) loadProfileDetail(profileKey);
  }, [profileKey, loadProfileDetail]);

  // Auto-match the motion profile to the typed animal (keyword resolution — same map the
  // design page uses, so "shark" → aquatic). Debounced; only re-runs when the animal text
  // changes, so a manual profile pick afterward sticks until the animal is edited again.
  useEffect(() => {
    const a = animal.trim();
    if (!a || !list) return;
    const t = setTimeout(async () => {
      try {
        const { profile } = await fetchMotions(a);
        if (profile && list.profiles.some((p) => p.key === profile)) {
          setProfileKey(profile);
          setMatchedProfileFor(a);
        }
      } catch { /* best-effort — the admin can still pick a profile manually */ }
    }, 500);
    return () => clearTimeout(t);
  }, [animal, list]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Second opinion: what a real BUILD would resolve this animal to. The match above is
  // the keyword path — instant and free, but NOT what a build uses; a build asks the AI
  // classifier and pins that key on the record. Longer debounce than the keyword match so
  // typing doesn't spend an AI call per keystroke, and the answer is displayed rather than
  // applied. Cleared on every edit so a stale verdict can't sit under a new animal.
  useEffect(() => {
    const a = animal.trim();
    setBuildMatch(null);
    if (!a) return;
    const t = setTimeout(() => {
      motionAdmin.classify(a)
        .then((c) => { if (c.animal.trim() === a) setBuildMatch(c); })
        .catch(() => { /* best-effort — the keyword match still stands */ });
    }, 900);
    return () => clearTimeout(t);
  }, [animal]);

  // The design vocabulary for the TYPED animal (§2.1). The designer keys this off its
  // reference; the Lab has free text and no reference, so it asks by name and the server
  // resolves the surface — a bird is offered plumage, a cat coat, an unknown creature
  // neither. Same debounce as the profile match, for the same reason.
  useEffect(() => {
    const a = animal.trim();
    let cancelled = false;
    const t = setTimeout(() => {
      fetchDesignAxes({ animal: a })
        .then((r) => { if (!cancelled) setAxes(r.axes); })
        .catch(() => { /* keep the previous menu; the server still filters picks */ });
    }, 500);
    return () => { cancelled = true; clearTimeout(t); };
  }, [animal]);

  async function uploadReference(file: File) {
    setErr(""); setNotice(""); setRefBusy(true);
    try {
      const r = await motionLab.uploadReference(file);
      clearRenders();                       // the base and every anchor are now stale
      setSource({ kind: "upload", reference_id: r.reference_id, url: r.url, upload: r });
      if (r.subject) setAnimal(r.subject);  // the captioner's noun, as the upload door would use it
      setNotice(r.usable
        ? `Triage accepted it — the captioner called it “${r.subject}”${r.features ? ` (${r.features})` : ""}.`
        : "Triage REJECTED this photo, so the real upload door would have no noun for it. Type one yourself.");
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "Upload failed.");
    } finally { setRefBusy(false); }
  }

  function clearRenders() {
    setBase(null);
    setCells((c) => Object.fromEntries(Object.entries(c).map(([n, cell]) =>
      [n, { ...cell, still: null, loop: null, packed: null, packError: "", metrics: null }])));
    // A DESIGN source is a redraw of the base still that just went stale, so it goes with
    // it; an UPLOAD source is a photo on the desk and stays (I12). The design PICKS stay
    // too — they are what you are iterating on.
    setSource((s) => (s?.kind === "design" ? null : s));
    setComposed("");
  }
  const patch = (name: string, p: Partial<Cell>) => setCells((c) => ({ ...c, [name]: { ...c[name], ...p } }));
  // What every anchor and loop draws from — the typed animal until a design replaces it
  // with the display name a build's record would now carry (labDraw.poseSubject).
  const subject = poseSubject(source, animal);

  // --- core ops: start a job, poll it (timer + phase), return the asset or null (canceled) ---
  async function doDrawBase(): Promise<LabAsset | null> {
    setBaseElapsed(0); setBasePhase("pending");
    // The base still's pose word IS base_pose (empty → the backend's "standing" default).
    const { job_id } = await motionLab.startStill(animal, basePose.trim(), seed,
      baseDrawOptions(source?.reference_id ?? null, baseDenoise));
    setBaseJob(job_id);
    try {
      const j = await pollJob(job_id, (t) => { setBaseElapsed(t.elapsed); setBasePhase(t.phase); });
      const a = j && assetOf(j);
      if (a) setBase(a);
      return a;
    } finally { setBaseJob(null); }
  }
  async function doDrawAnchor(name: string, clause: string): Promise<LabAsset | null> {
    patch(name, { elapsed: 0, phase: "pending" });
    // No draw options at all: an anchor is txt2img in the remix sentence whatever is
    // loaded (§2.6). It carries the SUBJECT, not the typed field — after a design that is
    // "white snow leopard", exactly what a build's reference record now says (poseSubject).
    const { job_id } = await motionLab.startStill(subject, clause, seed);
    patch(name, { jobId: job_id });
    try {
      const j = await pollJob(job_id, (t) => patch(name, { elapsed: t.elapsed, phase: t.phase }));
      const a = j && assetOf(j);
      if (a) patch(name, { still: a, loop: null, packed: null, packError: "", metrics: null });
      return a;
    } finally { patch(name, { jobId: null }); }
  }
  async function doAnimate(name: string, start: LabAsset): Promise<LabAsset | null> {
    patch(name, { elapsed: 0, phase: "pending" });
    // The loop prompt is compose_pose_prompt(subject, pose) — same subject as the anchor,
    // because a build passes one `description` to the whole of make_pet_zip.
    const { job_id } = await motionLab.startAnimate(start.asset_id, subject, profileKey, name, seed);
    patch(name, { jobId: job_id });
    try {
      // The raw tile renders while the packer is still running — a visible loop IS a
      // result, and it is the one you still have when the packer is the broken thing.
      const j = await pollJob(job_id, (t) => patch(name, {
        elapsed: t.elapsed, phase: t.phase, ...(t.url ? { loop: assetOf(t) } : null),
      }));
      const a = j && assetOf(j);
      if (j) patch(name, { loop: a, packed: packedOf(j), packError: j.pack_error ?? "", metrics: j.metrics });
      return a;
    } finally { patch(name, { jobId: null }); }
  }

  // --- per-cell buttons (concurrent: firing one does NOT block the others; they queue) ---
  async function drawBase() {
    setBaseBusy(true); setErr("");
    try { await doDrawBase(); } catch (e) { setErr(genErr(e)); } finally { setBaseBusy(false); }
  }

  /** Step 2, in the Lab: redraw the base still that is on screen toward the design
   *  (§2.3). This is the ONE draw the composed description is spent on, exactly as a
   *  build spends it once in `/api/preview`'s redraw — after which the result IS the
   *  design, replaces the base, and becomes what the next base draw restacks from (I6). */
  async function applyDesign() {
    if (!base) { setErr("Draw the base first — a design is a redraw of it."); return; }
    setDesignBusy(true); setErr(""); setNotice(""); setDesignElapsed(0); setDesignPhase("pending");
    try {
      const { job_id, description, subject: designed, min_strength } = await motionLab.startStill(
        animal, basePose.trim(), seed,
        baseDrawOptions(base.asset_id, designStrength,
                        { color, accessories, axis_picks: axisPicks, extra }));
      setDesignJob(job_id);
      setMinStrength(min_strength);
      const j = await pollJob(job_id, (t) => { setDesignElapsed(t.elapsed); setDesignPhase(t.phase); });
      const a = j && assetOf(j);
      if (a) {
        setBase(a);
        // The design's OUTPUT record: the still to restack from, and the subject every
        // later anchor/loop now draws from — a build's step-2 reference, in two fields.
        setSource({ kind: "design", reference_id: a.asset_id, url: a.url, description, subject: designed });
        setComposed(description);
      }
    } catch (e) { setErr(genErr(e)); }
    finally { setDesignBusy(false); setDesignJob(null); }
  }
  async function drawAnchor(name: string) {
    const clause = cells[name].clause.trim();
    if (!clause) return;
    patch(name, { busy: "draw" }); setErr("");
    try { await doDrawAnchor(name, clause); } catch (e) { setErr(genErr(e)); } finally { patch(name, { busy: "" }); }
  }
  async function animateOne(name: string) {
    const clause = cells[name].clause.trim();
    const start = clause ? cells[name].still : base;
    if (!start) { setErr(clause ? "Draw this pose's anchor first." : "Draw the base first."); return; }
    patch(name, { busy: "animate" }); setErr("");
    try { await doAnimate(name, start); } catch (e) { setErr(genErr(e)); } finally { patch(name, { busy: "" }); }
  }
  async function saveOne(name: string) {
    if (!detail) return;
    patch(name, { busy: "save" }); setErr(""); setNotice("");
    try {
      await motionAdmin.update(profileKey, profileWithClauses(detail.profile, { [name]: cells[name].clause }), detail.label);
      setNotice(`Saved ${profileKey}.${name} — live now.`);
      setDetail(await motionAdmin.get(profileKey));
    } catch (e) { setErr(saveErr(e)); } finally { patch(name, { busy: "" }); }
  }
  // AI draft of the pose clause (SPEC_MOTION_LAB §2). Best-effort: it fills the box;
  // the admin edits + re-runs. A fresh clause invalidates this column's renders.
  async function suggestClause(name: string) {
    patch(name, { busy: "suggest" }); setErr(""); setNotice("");
    try {
      const { clause } = await motionLab.suggestClause(animal, name, detail?.profile.movement_class ?? "");
      patch(name, { clause: clause.trim(), still: null, loop: null });
    } catch (e) { setErr(e instanceof AdminApiError ? e.message : "Suggest failed."); }
    finally { patch(name, { busy: "" }); }
  }
  // Revert an edited clause to the one saved in the profile (nothing was written, so this
  // is a pure local reset). Clears this column's now-mismatched renders.
  function revertClause(name: string) {
    patch(name, { clause: detail?.profile.poses[name]?.control?.pose ?? "", still: null, loop: null });
  }

  // --- Base Pose card: authored like a pose (clause + suggest + draw + save), minus the
  // animation — the base is a still, not a loop. It IS profile.base_pose (§SPEC_BUNDLE_MOTION). ---
  async function suggestBasePose() {
    setBaseKind("suggest"); setErr(""); setNotice("");
    try {
      const { clause } = await motionLab.suggestClause(animal, "base resting pose", detail?.profile.movement_class ?? "");
      setBasePose(clause.trim()); setBase(null);
    } catch (e) { setErr(e instanceof AdminApiError ? e.message : "Suggest failed."); }
    finally { setBaseKind(""); }
  }
  function revertBasePose() {
    setBasePose(detail?.profile.base_pose ?? "standing"); setBase(null);
  }
  async function saveBasePose() {
    if (!detail) return;
    setBaseKind("save"); setErr(""); setNotice("");
    try {
      const next = structuredClone(detail.profile);
      next.base_pose = basePose.trim() || "standing";
      await motionAdmin.update(profileKey, next, detail.label);
      setNotice(`Saved base pose to ${profileKey} — live now.`);
      setDetail(await motionAdmin.get(profileKey));
    } catch (e) { setErr(saveErr(e)); } finally { setBaseKind(""); }
  }

  // --- "all" (CONCURRENT: fire every column at once so the backend spreads them
  // across GPUs; extras queue in ComfyUI. One column failing/canceling doesn't stop
  // the others) ---
  async function drawAllAnchors() {
    setBusyAll("draw"); setErr("");
    try {
      await Promise.all(columns.filter((n) => cells[n].clause.trim()).map(async (name) => {
        try { patch(name, { busy: "draw" }); await doDrawAnchor(name, cells[name].clause.trim()); }
        catch (e) { setErr(genErr(e)); }
        finally { patch(name, { busy: "" }); }
      }));
    } finally { setBusyAll(""); }
  }
  async function animateAll() {
    setBusyAll("animate"); setErr("");
    try {
      const b = base ?? await doDrawBase();
      if (!b) return;
      await Promise.all(columns.map(async (name) => {
        try {
          const clause = cells[name].clause.trim();
          let start = clause ? cells[name].still : b;
          if (clause && !start) { patch(name, { busy: "draw" }); start = await doDrawAnchor(name, clause); }
          if (!start) return;
          patch(name, { busy: "animate" });
          await doAnimate(name, start);
        } catch (e) { setErr(genErr(e)); }
        finally { patch(name, { busy: "" }); }
      }));
    } finally { setBusyAll(""); }
  }
  async function saveAll() {
    if (!detail) return;
    setBusyAll("save"); setErr(""); setNotice("");
    try {
      const clauses = Object.fromEntries(columns.map((n) => [n, cells[n].clause]));
      const next = profileWithClauses(detail.profile, clauses);
      next.base_pose = basePose.trim() || "standing";   // the base still's posture is profile content too
      await motionAdmin.update(profileKey, next, detail.label);
      setNotice(`Saved ${columns.length} pose(s) + base pose to ${profileKey} — live now.`);
      setDetail(await motionAdmin.get(profileKey));
    } catch (e) { setErr(saveErr(e)); } finally { setBusyAll(""); }
  }

  // --- profile CRUD for the selected profile (same motion_admin write the Motions page uses) ---
  const refreshList = useCallback(() => motionAdmin.list().then(setList).catch(() => {}), []);

  async function openEditProfile() {
    setErr(""); setEditErrors([]);
    try {
      const d = await motionAdmin.get(profileKey);
      setEditDraft({ profile: d.profile, label: d.label, editingKey: profileKey });
    } catch { setErr("Could not load the profile to edit."); }
  }
  async function saveEditProfile() {
    if (!editDraft?.editingKey) return;
    setEditBusy(true); setEditErrors([]);
    try {
      await motionAdmin.update(editDraft.editingKey, editDraft.profile, editDraft.label);
      setNotice(`Saved ${editDraft.editingKey} — live now.`);
      setEditDraft(null);
      await refreshList();
      loadProfileDetail(profileKey, false);   // rebuild the pose menu; keep the drawn base
    } catch (e) {
      setEditErrors(e instanceof AdminApiError ? (e.errors.length ? e.errors : [e.message]) : ["Save failed."]);
    } finally { setEditBusy(false); }
  }
  async function duplicateProfile() {
    const newKey = window.prompt(`Duplicate "${profileKey}" as (new key, lowercase/underscore):`, `${profileKey}_copy`);
    if (!newKey) return;
    setErr("");
    try {
      await motionAdmin.duplicate(profileKey, newKey, `Copy of ${profileKey}`);
      await refreshList();
      setProfileKey(newKey);   // switch the Lab to the copy so you can tune it immediately
      setNotice(`Duplicated to "${newKey}" — tune it, then Save.`);
    } catch (e) { setErr(e instanceof AdminApiError ? e.message : "Duplicate failed."); }
  }
  async function deleteProfile() {
    setConfirmDel(false);
    const deleted = profileKey;
    setErr("");
    try {
      await motionAdmin.remove(deleted);
      const l = await motionAdmin.list(); setList(l);
      setProfileKey(l.default || l.profiles[0]?.key || "");   // fall back to the default
      setNotice(`Deleted "${deleted}".`);
    } catch (e) { setErr(e instanceof AdminApiError ? e.message : "Delete failed."); }
  }

  const cancelJob = (jobId: string | null) => { if (jobId) motionLab.cancel(jobId).catch(() => {}); };

  if (gate === "checking") {
    return <main><p className="mono text-sm" style={{ color: "var(--faint)" }}>Checking admin access…</p></main>;
  }
  if (gate === "denied") {
    return (
      <main>
        <h1 className="mb-2 text-2xl" style={{ color: "var(--heading)" }}>Motion Lab unavailable</h1>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          The Lab is a DatsMe-admin, GPU-dev-box tool — it needs the local generation backend and admin access.
        </p>
        <Link href="/admin/motions" className="mono mt-4 inline-block text-sm underline" style={{ color: "var(--accent)" }}>← Motion profiles</Link>
      </main>
    );
  }

  // The photo behind an `upload` source — the only kind that has a triage verdict to show.
  const upload = source?.kind === "upload" ? source.upload : null;
  // "Has the operator designed anything?" — the same predicate the server applies (a pick
  // equal to its axis default is no design at all), so the ✎ marker and the composed
  // string agree about whether step 2 was used.
  const designed = !!(color || accessories.length || extra.trim()
    || Object.entries(axisPicks).some(([axis, key]) => key !== axes.find((a) => a.axis === axis)?.default));
  const enabledPoses = detail ? CANONICAL_POSES.filter((n) => detail.profile.poses[n]?.enabled) : [];
  const columns = CANONICAL_POSES.filter((n) => selected.includes(n) && cells[n]);
  const anyBusy = baseBusy || designBusy || busyAll !== "" || Object.values(cells).some((c) => c.busy);
  const baseDirty = basePose.trim() !== (detail?.profile.base_pose ?? "standing").trim();
  const anyDirty = baseDirty || columns.some((n) => cells[n].clause.trim() !== (detail?.profile.poses[n]?.control?.pose ?? "").trim());
  const current = list?.profiles.find((p) => p.key === profileKey);
  const canWrite = !!list?.writable;
  const canDelete = canWrite && !!current && !current.is_default && current.pinned_by.length === 0;

  return (
    <main>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl" style={{ color: "var(--heading)" }}>Motion Lab</h1>
        <Link href="/admin/motions" className="mono text-sm underline" style={{ color: "var(--accent)" }}>← Motion profiles</Link>
      </div>
      <p className="mono mb-4 text-xs" style={{ color: "var(--faint)" }}>
        Author multiple poses from one base + seed and compare them side by side — catch colour/style drift before you save.
      </p>

      {notice && <div className="mono mb-3 text-sm" style={{ color: "var(--green)" }}>{notice}</div>}
      {err && <div className="mono mb-3 text-sm" style={{ color: "var(--accent)" }}>{err}</div>}

      {/* Setup — line 1 ANIMATION (the shared base still), line 2 MOTION (profile + its CRUD) */}
      <div className="card mb-3 flex flex-col gap-3 p-4">
        {/* line 1 — animation base */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label className={labelCls} style={{ color: "var(--muted)" }}>animal</label>
            <input value={animal} onChange={(e) => { setAnimal(e.target.value); clearRenders(); }}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
          </div>
          <div className="w-20">
            <label className={labelCls} style={{ color: "var(--muted)" }}>seed</label>
            <input type="number" value={seed} onChange={(e) => { setSeed(Number(e.target.value) || DEFAULT_SEED); clearRenders(); }}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
          </div>
          <div>
            <label className={labelCls} style={{ color: "var(--muted)" }}>base still (shared)</label>
            <div className="flex items-center gap-2">
              <CellImg asset={base} size={64} placeholder={baseBusy ? (basePhase === "pending" ? "…" : `${baseElapsed}s`) : "—"} />
              <button onClick={drawBase} disabled={baseBusy || designBusy}
                className="mono rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
                style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
                {runLabel(baseBusy, basePhase, baseElapsed, "Drawing", base ? "Redraw" : "Draw base")}
              </button>
              {baseBusy && <CancelBtn onClick={() => cancelJob(baseJob)} />}
            </div>
          </div>
        </div>

        {/* Upload door parity. A photo puts the base draw on the img2img path a photo pet
            (and a designed one) takes — the anchors are unaffected either way (§2.6). */}
        <div className="flex flex-wrap items-center gap-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
          <span className="mono text-xs" style={{ color: "var(--muted)" }}>from a photo</span>
          <label className="mono cursor-pointer rounded-lg border px-3 py-1.5 text-xs"
            style={{ color: "var(--accent)", borderColor: "var(--line)" }}>
            {refBusy ? "reading…" : upload ? "replace" : "upload"}
            <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden"
              disabled={refBusy}
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadReference(f); }} />
          </label>
          {upload && (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={motionLab.assetUrl(upload.url)} alt="reference" width={48} height={48}
                className="rounded" style={{ objectFit: "cover", border: "1px solid var(--line)" }} />
              <span className="mono text-xs" style={{ color: upload.usable ? "var(--green)" : "var(--orange)" }}>
                {upload.usable ? `triage ok — “${upload.subject}”` : "triage REJECTED — no noun from the AI"}
              </span>
              <button onClick={() => { setSource(null); clearRenders(); }}
                className="mono rounded border px-2 py-1 text-xs"
                style={{ color: "var(--faint)", borderColor: "var(--line)" }}>clear</button>
            </>
          )}
          {source && (
            <label className="mono flex items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
              base denoise
              <input type="range" min={MIN_DENOISE} max={MAX_DENOISE} step={DENOISE_STEP} value={baseDenoise}
                onChange={(e) => { setBaseDenoise(Number(e.target.value)); setBase(null); }} />
              <span style={{ color: "var(--heading)" }}>{baseDenoise.toFixed(2)}</span>
            </label>
          )}
          {source && (
            <span className="mono w-full text-xs" style={{ color: "var(--faint)" }}>
              only the base is redrawn from {source.kind === "upload" ? "the photo" : "the design"};
              anchors stay txt2img from the subject, as every build draws them
            </span>
          )}
        </div>

        {/* line 2 — motion profile + CRUD (the same Edit/Duplicate/Delete as the Motions page) */}
        <div className="flex flex-wrap items-end gap-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
          <div className="w-44">
            <label className={labelCls} style={{ color: "var(--muted)" }}>motion profile</label>
            <select value={profileKey} onChange={(e) => { setProfileKey(e.target.value); setMatchedProfileFor(""); }}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
              {list?.profiles.map((p) => <option key={p.key} value={p.key}>{p.key}</option>)}
            </select>
          </div>
          {matchedProfileFor && matchedProfileFor === animal.trim() && (
            <span className="mono pb-2 text-xs" style={{ color: "var(--faint)" }}>↳ auto-matched from “{matchedProfileFor}” (keyword)</span>
          )}
          {/* What a real BUILD would pick. Shown, never applied: the Lab's job is to try
              pairings that shouldn't work, so it must not overrule a deliberate choice —
              it just refuses to let a mismatch be invisible. */}
          {buildMatch && buildMatch.animal.trim() === animal.trim() && (
            buildMatch.profile_key === profileKey ? (
              <span className="mono pb-2 text-xs" style={{ color: "var(--green)" }}>
                ✓ a real build would use this too ({buildMatch.source})
              </span>
            ) : (
              <span className="mono flex items-center gap-2 pb-2 text-xs" style={{ color: "var(--orange)" }}>
                ⚠ a real build would use {buildMatch.profile_key} ({buildMatch.source})
                <button type="button"
                  onClick={() => { setProfileKey(buildMatch.profile_key); setMatchedProfileFor(""); }}
                  className="mono rounded border px-2 py-0.5 text-xs"
                  style={{ color: "var(--orange)", borderColor: "rgba(251,146,60,0.5)" }}>
                  use it
                </button>
              </span>
            )
          )}
          <div className="flex items-center gap-2 pb-0.5">
            <button onClick={openEditProfile} disabled={!profileKey}
              className="mono rounded-lg border px-3 py-2 text-xs disabled:opacity-40"
              style={{ color: "var(--accent)", borderColor: "var(--line)" }}>Edit</button>
            <button onClick={duplicateProfile} disabled={!canWrite || !profileKey}
              className="mono rounded-lg border px-3 py-2 text-xs disabled:opacity-40"
              style={{ color: "var(--gold)", borderColor: "var(--line)" }}>Duplicate</button>
            <button onClick={() => setConfirmDel(true)} disabled={!canDelete}
              className="mono rounded-lg border px-3 py-2 text-xs disabled:opacity-40"
              style={{ color: "var(--accent)", borderColor: "var(--line)" }}
              title={current?.is_default ? "the default profile can't be deleted" : (current?.pinned_by.length ? "pinned by a catalog entry" : undefined)}>
              Delete</button>
            {!canWrite && <span className="mono text-xs" style={{ color: "var(--orange)" }}>read-only</span>}
          </div>
        </div>
      </div>

      {/* STEP 2 — its OWN card, in the design tint (.card-design), directly under the
          setup it follows. It began as another border-top row inside the card above and
          that was wrong twice over: it split the setup card's own three rows in half, and
          "what does the pet look like" read as one more piece of "which animal, which
          profile" when it is a different kind of decision entirely. One card, one
          question — the same rule the three-step designer is built on. */}
      <div className="card card-design mb-3 flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={() => setDesignOpen((v) => !v)}
            className="mono rounded-lg border px-3 py-1.5 text-xs"
            style={{ color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}>
            {designOpen ? "▾" : "▸"} design (step 2){designed ? " ✎" : ""}
          </button>
          <span className="mono text-xs" style={{ color: "var(--faint)" }}>
            what the pet LOOKS like — redraws the base still; the poses below draw from{" "}
            <span style={{ color: source?.kind === "design" ? "var(--gold)" : "var(--faint)" }}>
              “{subject || "…"}”
            </span>
            {source?.kind === "design" && " (the colour rides along; the rest was spent on the redraw)"}
          </span>
          {/* The RESULT, where the button that produced it is. "Apply design" replaces the
              shared base still (I6), whose thumbnail lives in the setup card — so without
              this tile the operator presses Redraw and the output appears in a different
              card, often scrolled off screen. A redraw you cannot see is not a preview. */}
          <div className="ml-auto flex items-center gap-3">
            <div className="flex flex-col items-center gap-1">
              <CellImg asset={base} size={72}
                placeholder={designBusy ? (designPhase === "pending" ? "…" : `${designElapsed}s`) : "no base"} />
              <span className="mono text-xs" style={{ color: "var(--faint)" }}>
                {composed ? "designed" : "base still"}
              </span>
            </div>
            <button onClick={applyDesign} disabled={designBusy || baseBusy || !base}
              className="mono rounded-lg border px-4 py-1.5 text-xs font-semibold disabled:opacity-45"
              style={{ background: "rgba(167,139,250,0.14)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.5)" }}
              title={base ? undefined : "draw the base first — a design is a redraw of it"}>
              {runLabel(designBusy, designPhase, designElapsed, "Redrawing", "Apply design")}
            </button>
            {designBusy && <CancelBtn onClick={() => cancelJob(designJob)} />}
          </div>
        </div>
        {designOpen && (
          <DesignStep
            color={color} accessories={accessories} axisPicks={axisPicks} extra={extra}
            strength={designStrength} axes={axes} minStrength={minStrength}
            onColor={setColor}
            onAccessory={(a) => setAccessories((list) => list.includes(a)
              ? list.filter((x) => x !== a)
              : [...list, a].slice(0, MAX_ACCESSORIES))}
            onAxisPick={(axis, key) => setAxisPicks((p) => ({ ...p, [axis]: key }))}
            onExtra={setExtra}
            onStrength={setDesignStrength}
          />
        )}
        {composed && (
          <div className="mono border-t pt-2 text-xs" style={{ borderColor: "rgba(167,139,250,0.25)", color: "var(--faint)" }}>
            spent on the base: <span style={{ color: "var(--gold)" }}>“{composed}”</span>
          </div>
        )}
      </div>

      {/* Poses — right below the motion profile: the available poses come from it */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="mono text-xs" style={{ color: "var(--muted)" }}>poses:</span>
        {/* Base pill — first, before Walk. Its card is closed by default; select it to edit the base pose. */}
        {detail && (
          <button onClick={() => setBaseSelected((v) => !v)}
            className="mono rounded-full border px-3 py-1 text-xs"
            style={baseSelected
              ? { background: "rgba(99,102,241,0.18)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.5)" }
              : { color: "var(--faint)", borderColor: "var(--line)" }}>
            Base{(detail.profile.base_pose ?? "standing") !== "standing" ? " ✎" : ""}
          </button>
        )}
        {enabledPoses.map((n) => {
          const on = selected.includes(n);
          const hasClause = cells[n]?.clause.trim() || detail?.profile.poses[n]?.control?.kind === "pose_prompt";
          return (
            <button key={n} onClick={() => setSelected((s) => on ? s.filter((x) => x !== n) : [...s, n])}
              className="mono rounded-full border px-3 py-1 text-xs capitalize"
              style={on
                ? { background: "rgba(99,102,241,0.18)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.5)" }
                : { color: "var(--faint)", borderColor: "var(--line)" }}>
              {n}{hasClause ? " ✎" : ""}
            </button>
          );
        })}
      </div>

      {/* GPUs — the Lab dispatches across ComfyUI instances; start_comfyui_gpu1.sh brings up GPU 1 */}
      {endpoints.length > 1 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="mono text-xs" style={{ color: "var(--muted)" }}>GPUs:</span>
          {endpoints.map((e) => (
            <button key={e.index} onClick={() => toggleGpu(e.index)}
              title={e.healthy ? `${e.label} — ready` : `${e.label} — not running (start_comfyui_gpu1.sh)`}
              className="mono flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs"
              style={e.active
                ? { background: "rgba(99,102,241,0.18)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.5)" }
                : { color: "var(--faint)", borderColor: "var(--line)" }}>
              <span style={{ width: 7, height: 7, borderRadius: 9999, display: "inline-block", background: e.healthy ? "var(--green)" : "#f87171" }} />
              {e.label}{e.inflight ? ` · ${e.inflight}` : ""}
            </button>
          ))}
          <span className="mono text-xs" style={{ color: "var(--faint)" }}>
            {endpoints.filter((e) => e.active && e.healthy).length > 1 ? "· two at a time (~2×)" : "· one at a time"}
          </span>
        </div>
      )}

      {/* Global actions */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <BatchBtn label="Draw all anchors" busy={busyAll === "draw"} onClick={drawAllAnchors} disabled={anyBusy || !columns.length} />
        <BatchBtn label="Animate all" busy={busyAll === "animate"} onClick={animateAll} disabled={anyBusy || !columns.length} />
        <button onClick={() => setConfirmSave({ kind: "all" })} disabled={busyAll === "save" || !detail || !list?.writable || !anyDirty}
          className="mono rounded-lg py-2 px-4 text-sm font-bold disabled:opacity-45"
          style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
          {busyAll === "save" ? "Saving…" : "Save all"}
        </button>
        {anyDirty && <span className="mono text-xs" style={{ color: "var(--gold)" }}>unsaved changes</span>}
        {!list?.writable && <span className="mono text-xs" style={{ color: "var(--orange)" }}>read-only instance</span>}
      </div>

      {/* Columns */}
      <div className="flex gap-3 overflow-x-auto pb-3">
        {/* Base Pose — the first card, shown only when the Base pill is selected. Authored like a
            pose (clause + AI suggest + draw + save), but with NO animation: the base is the shared
            still every clause-less pose draws from. */}
        {detail && baseSelected && (
          <div className="card w-56 shrink-0 overflow-hidden p-0" style={{ borderColor: "rgba(99,102,241,0.45)" }}>
            <div className="flex items-center justify-between px-3 pt-3">
              <span className="font-semibold" style={{ color: "var(--heading)" }}>Base Pose</span>
              <span className="mono text-xs" style={{ color: "var(--accent)" }}>shared</span>
            </div>
            <div className="m-3 rounded-lg p-2" style={{ background: "#151515", border: "1px solid var(--line)" }}>
              <div className="mono mb-1 flex items-center justify-between gap-2 text-xs" style={{ color: "var(--faint)" }}>
                <span>base pose → base still</span>
                <div className="flex shrink-0 items-center gap-1">
                  {baseDirty && (
                    <button onClick={revertBasePose} disabled={baseBusy || baseKind !== ""}
                      className="mono rounded border px-1.5 py-0.5 text-[10px] disabled:opacity-40"
                      style={{ color: "var(--muted)", borderColor: "var(--line)" }}
                      title="Revert to the saved base pose">↺ revert</button>
                  )}
                  <button onClick={suggestBasePose} disabled={baseBusy || baseKind !== ""}
                    className="mono rounded border px-1.5 py-0.5 text-[10px] disabled:opacity-40"
                    style={{ color: "var(--gold)", borderColor: "var(--line)" }}
                    title="Draft a base pose with AI, then edit it">
                    {baseKind === "suggest" ? "…" : "✨ suggest"}
                  </button>
                </div>
              </div>
              <textarea value={basePose} onChange={(e) => { setBasePose(e.target.value); setBase(null); }}
                placeholder="base pose — e.g. standing · or: swimming, body horizontal and level"
                className="mono mb-2 min-h-[44px] w-full resize-y rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
              <CellImg asset={base} size={168}
                placeholder={baseBusy ? runLabel(true, basePhase, baseElapsed, "Drawing", "") : "Draw base"} />
              <ActionRow label={runLabel(baseBusy, basePhase, baseElapsed, "Drawing", "Draw base")}
                disabled={baseBusy || baseKind !== ""} onClick={drawBase} tone="draw"
                onCancel={baseBusy ? () => cancelJob(baseJob) : undefined} />
            </div>
            <div className="px-3 pb-3">
              <button onClick={() => setConfirmSave({ kind: "base" })} disabled={baseKind === "save" || !list?.writable || !baseDirty}
                className="mono w-full rounded-lg py-1.5 text-xs font-bold disabled:opacity-40"
                style={baseDirty
                  ? { background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)", border: "1px solid rgba(99,102,241,0.5)" }
                  : { background: "#1c1c1c", color: "var(--faint)", border: "1px solid var(--line)" }}>
                {baseKind === "save" ? "Saving…" : baseDirty ? "Save base pose" : "Saved"}
              </button>
            </div>
          </div>
        )}
        {columns.map((name) => {
          const cell = cells[name];
          const isAnchored = !!cell.clause.trim();
          const start = isAnchored ? cell.still : base;
          const dirty = cell.clause.trim() !== (detail?.profile.poses[name]?.control?.pose ?? "").trim();
          return (
            <div key={name} className="card w-56 shrink-0 overflow-hidden p-0">
              <div className="flex items-center justify-between px-3 pt-3">
                <span className="font-semibold capitalize" style={{ color: "var(--heading)" }}>{name}</span>
                <span className="mono text-xs" style={{ color: isAnchored ? "var(--accent)" : "var(--faint)" }}>{isAnchored ? "anchor" : "base"}</span>
              </div>

              {/* Anchor section */}
              <div className="m-3 rounded-lg p-2" style={{ background: "#151515", border: "1px solid var(--line)" }}>
                <div className="mono mb-1 flex items-center justify-between gap-2 text-xs" style={{ color: "var(--faint)" }}>
                  <span>pose clause → {isAnchored ? "anchor still" : "uses base"}</span>
                  <div className="flex shrink-0 items-center gap-1">
                    {dirty && (
                      <button onClick={() => revertClause(name)} disabled={cell.busy !== ""}
                        className="mono rounded border px-1.5 py-0.5 text-[10px] disabled:opacity-40"
                        style={{ color: "var(--muted)", borderColor: "var(--line)" }}
                        title="Revert to the saved clause (nothing was saved yet)">
                        ↺ revert
                      </button>
                    )}
                    <button onClick={() => suggestClause(name)} disabled={cell.busy !== ""}
                      className="mono rounded border px-1.5 py-0.5 text-[10px] disabled:opacity-40"
                      style={{ color: "var(--gold)", borderColor: "var(--line)" }}
                      title="Draft a pose clause with AI, then edit it">
                      {cell.busy === "suggest" ? "…" : "✨ suggest"}
                    </button>
                  </div>
                </div>
                <textarea value={cell.clause} onChange={(e) => patch(name, { clause: e.target.value })}
                  placeholder="pose clause (empty = uses base)"
                  className="mono mb-2 min-h-[44px] w-full resize-y rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
                <CellImg asset={start} size={168}
                  placeholder={cell.busy === "draw" ? runLabel(true, cell.phase, cell.elapsed, "Drawing", "") : isAnchored ? "Draw anchor" : "Draw base"} />
                <ActionRow label={runLabel(cell.busy === "draw", cell.phase, cell.elapsed, "Drawing", "Draw anchor")}
                  disabled={cell.busy !== "" || !isAnchored} onClick={() => drawAnchor(name)} tone="draw"
                  onCancel={cell.busy === "draw" ? () => cancelJob(cell.jobId) : undefined} />
              </div>

              {/* Animation section — visually distinct (green). TWO tiles, and they are the
                  instrument (SPEC_MOTION_LAB_DESIGN_PARITY §2.5): the raw loop as ComfyUI
                  made it, then the SAME animation packed. Whatever the packer did to the pet
                  is the visible difference between them, in one run — which is what answers
                  "which step caused it". Same 40 s of GPU, no A/B to set up. */}
              <div className="m-3 mt-0 rounded-lg p-2" style={{ background: "rgba(52,211,153,0.06)", border: "1px solid rgba(52,211,153,0.22)" }}>
                <div className="mono mb-1 text-xs font-semibold" style={{ color: "var(--green)" }}>▸ animation</div>
                <CellImg asset={cell.loop} size={168}
                  placeholder={cell.busy === "animate" ? runLabel(true, cell.phase, cell.elapsed, "Animating", "") : "Animate"} />

                {/* The packed tile appears WHEN IT APPEARS: the loop is published first and
                    the pack follows (~6 s), so the raw tile renders while the packer is still
                    running. Holding both back for one atomic update would cost you the result
                    you still have when the packer is the broken thing. */}
                <div className="mono mb-1 mt-2 text-xs font-semibold" style={{ color: "var(--gold)" }}>▸ packed</div>
                {cell.packed ? (
                  <div className="overflow-hidden rounded-lg" style={{ border: "1px solid var(--line)", width: 168, height: 168 }}>
                    <PosePlayer source={cell.packed} pose={name} size={168} checkered />
                  </div>
                ) : (
                  <div className="mono flex items-center justify-center rounded-lg px-2 text-center text-xs"
                    style={{ width: 168, height: 168, color: cell.packError ? "var(--orange)" : "var(--faint)",
                             background: "#151515", border: "1px dashed var(--line)" }}>
                    {cell.packError
                      ? `packing failed: ${cell.packError}`
                      : cell.busy === "animate" && cell.phase === "packing" ? "packing…" : "—"}
                  </div>
                )}
                {/* A number beside the picture is what turns "that looks off" into a report —
                    and it comes from the same function scripts/probe_matte_fill.py prints. */}
                {cell.metrics && (
                  <div className="mono mt-1 text-xs"
                    style={{ color: cell.metrics.hard_zero_px ? "var(--orange)" : "var(--green)" }}>
                    {cell.metrics.line}
                  </div>
                )}
                <ActionRow label={runLabel(cell.busy === "animate", cell.phase, cell.elapsed, "Animating", "Animate")}
                  disabled={cell.busy !== "" || !start} onClick={() => animateOne(name)} tone="animate"
                  onCancel={cell.busy === "animate" ? () => cancelJob(cell.jobId) : undefined} />
              </div>

              <div className="px-3 pb-3">
                <button onClick={() => setConfirmSave({ kind: "one", name })} disabled={cell.busy === "save" || !list?.writable || !dirty}
                  className="mono w-full rounded-lg py-1.5 text-xs font-bold disabled:opacity-40"
                  style={dirty
                    ? { background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)", border: "1px solid rgba(99,102,241,0.5)" }
                    : { background: "#1c1c1c", color: "var(--faint)", border: "1px solid var(--line)" }}>
                  {cell.busy === "save" ? "Saving…" : dirty ? "Save clause" : "Saved"}
                </button>
              </div>
            </div>
          );
        })}
        {!columns.length && !baseSelected && (
          <div className="mono flex h-40 w-full items-center justify-center rounded-lg text-xs"
            style={{ color: "var(--faint)", background: "#151515", border: "1px dashed var(--line)" }}>
            Select one or more poses above.
          </div>
        )}
      </div>

      {/* Inline profile editor — the SAME ProfileEditor the Motions page uses, in a modal */}
      <ModalOverlay open={!!editDraft} onClose={() => { setEditDraft(null); setEditErrors([]); }}
        labelledBy="profile-editor-title" maxWidth="max-w-2xl">
        {editDraft && (
          <ProfileEditor draft={editDraft} setDraft={setEditDraft} errors={editErrors} busy={editBusy}
            defaultKey={list?.default ?? ""} onSave={saveEditProfile}
            onCancel={() => { setEditDraft(null); setEditErrors([]); }} />
        )}
      </ModalOverlay>
      <ConfirmModal open={confirmDel} title={`Delete "${profileKey}"?`}
        body="This removes the profile file and its registry entry. Animals that resolved to it fall back to a coarser profile."
        onConfirm={deleteProfile} onCancel={() => setConfirmDel(false)} />
      {/* Save writes to the motion profile (overwriting the stored clause) — confirm it. */}
      <ConfirmModal open={!!confirmSave} tone="primary"
        title={confirmSave?.kind === "all"
          ? `Save base pose + all clauses to "${profileKey}"?`
          : confirmSave?.kind === "base"
          ? `Save base pose to "${profileKey}"?`
          : `Save clause to "${profileKey}.${confirmSave?.name}"?`}
        body={confirmSave?.kind === "all"
          ? `This writes the base pose and the edited pose clauses into the "${profileKey}" motion profile, OVERWRITING their current values. It goes live immediately for every animal that uses this profile.`
          : confirmSave?.kind === "base"
          ? `This writes the base pose — the posture the shared base still is drawn in — into the "${profileKey}" motion profile, OVERWRITING its current value. It goes live immediately for every animal that uses this profile.`
          : `This writes the clause into ${profileKey}.${confirmSave?.name} in the "${profileKey}" motion profile, OVERWRITING its current clause. It goes live immediately for every animal that uses this profile.`}
        confirmLabel={confirmSave?.kind === "all" ? "Save all to profile" : confirmSave?.kind === "base" ? "Save base pose" : "Save to profile"}
        onConfirm={() => { const c = confirmSave; setConfirmSave(null); if (c?.kind === "all") saveAll(); else if (c?.kind === "base") saveBasePose(); else if (c?.name) saveOne(c.name); }}
        onCancel={() => setConfirmSave(null)} />
    </main>
  );
}

function BatchBtn({ label, busy, onClick, disabled }: { label: string; busy: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={busy || disabled}
      className="mono shrink-0 rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
      style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
      {busy ? "Running…" : label}
    </button>
  );
}

function CancelBtn({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} title="Cancel"
      className="mono shrink-0 rounded-lg border px-3 py-2 text-sm font-semibold"
      style={{ background: "rgba(239,68,68,0.12)", color: "#f87171", borderColor: "rgba(239,68,68,0.4)" }}>Cancel</button>
  );
}

function ActionRow({ label, disabled, onClick, onCancel, tone }: {
  label: string; disabled: boolean; onClick: () => void; onCancel?: () => void; tone: "draw" | "animate";
}) {
  // Filled buttons, distinct from the card background — draw = indigo, animate = green
  // (matching its green animation section).
  const btn = tone === "animate"
    ? { background: "rgba(52,211,153,0.16)", color: "var(--green)", borderColor: "rgba(52,211,153,0.45)" }
    : { background: "rgba(99,102,241,0.18)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.5)" };
  return (
    <div className="mt-2 flex items-center gap-1">
      <button onClick={onClick} disabled={disabled}
        className="mono flex-1 rounded border px-2 py-1 text-xs font-semibold disabled:opacity-40"
        style={btn}>{label}</button>
      {onCancel && (
        <button onClick={onCancel} title="Cancel"
          className="mono rounded border px-2 py-1 text-xs"
          style={{ color: "#f87171", borderColor: "rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.12)" }}>✕</button>
      )}
    </div>
  );
}

function CellImg({ asset, size, placeholder }: { asset: LabAsset | null; size: number; placeholder: string }) {
  if (!asset) {
    return <div className="mono flex items-center justify-center rounded-lg text-center text-xs"
      style={{ width: size, height: size, color: "var(--faint)", background: "#151515", border: "1px dashed var(--line)" }}>
      {placeholder}
    </div>;
  }
  return (
    <div className="overflow-hidden rounded-lg" style={{ width: size, height: size, background: "#fff", border: "1px solid var(--line)" }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={motionLab.assetUrl(asset.url)} alt="" className="h-full w-full object-contain" />
    </div>
  );
}
