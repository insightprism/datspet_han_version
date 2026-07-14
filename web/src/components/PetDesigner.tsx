"use client";

/**
 * <PetDesigner> — the shared generation core of the designer surface
 * (SPEC_PET_DESIGNER_PLATFORM §3.1). Extracted from the original `/design` page
 * so every themed page (Cat World, Dog World, …) and the General page compose
 * the SAME controls: base picker, color, accessories, strength, pose selector +
 * cost hint, preview, submit, and the job result.
 *
 * §0 boundary: this is the "generation CONTRACT" half — it never owns page
 * theme/chrome. A page renders its own header/background and drops <PetDesigner>
 * in. The one seam a themed page needs is the BASE SOURCE:
 *
 *   - base={{ kind: "house" }}   (default) — General: redesign any house pet,
 *     species + pose menu keyed off the selected pet (today's behavior, verbatim).
 *   - base={{ kind: "catalog", animal, breeds, motionProfile }} — themed: a
 *     curated catalog breed is the img2img source (§4.3); the base image shows
 *     instantly and the pinned motion_profile drives the pose menu + build (§4.2).
 *
 * Everything downstream of the base pick (color/accessory/strength/pose/preview/
 * submit) is identical for both sources — that identity is the whole point.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listPets, previewDesign, previewImageUrl, fetchMotions,
  catalogBaseImageUrl, fetchEntitlement,
  type PetSummary, type MotionMenu, type CatalogBreed, type Entitlement,
} from "@/lib/api";
import { usePetJob } from "@/hooks/usePetJob";
import PetJobResult from "@/components/PetJobResult";
import PetThumbnail from "@/components/PetThumbnail";

// Named colors the prompt understands, with swatches for the picker.
const COLORS = [
  { name: "red", css: "#ef4444" },
  { name: "orange", css: "#f97316" },
  { name: "golden", css: "#eab308" },
  { name: "green", css: "#22c55e" },
  { name: "emerald", css: "#10b981" },
  { name: "teal", css: "#14b8a6" },
  { name: "sky blue", css: "#38bdf8" },
  { name: "blue", css: "#3b82f6" },
  { name: "indigo", css: "#6366f1" },
  { name: "purple", css: "#a855f7" },
  { name: "pink", css: "#ec4899" },
  { name: "rose", css: "#fb7185" },
  { name: "brown", css: "#926b4a" },
  { name: "cream", css: "#f5e9d3" },
  { name: "white", css: "#f8fafc" },
  { name: "black", css: "#1e1e1e" },
] as const;

// The accessory catalog — 25 small, wearable, side-profile-friendly items.
const ACCESSORIES = [
  "wizard hat", "party hat", "top hat", "baseball cap", "cowboy hat",
  "beanie", "crown", "flower crown", "santa hat", "red scarf",
  "blue scarf", "rainbow scarf", "bow tie", "bandana", "cape",
  "sunglasses", "round glasses", "monocle", "eye patch", "gold necklace",
  "headphones", "sneakers", "rain boots", "cowboy boots", "tiny backpack",
] as const;

const MAX_ACCESSORIES = 3;

// How far the redraw drifts from the base pet. Calibrated empirically:
// below ~0.85 the base image's original colors win over the requested ones.
const STRENGTHS = [
  { label: "subtle", value: 0.78, hint: "small tweaks" },
  { label: "balanced", value: 0.85, hint: "recolor/restyle" },
  { label: "strong", value: 0.9, hint: "redesign" },
] as const;

// The pose cap is the caller's RESOLVED tier entitlement (§8.6) — fetched from
// the server, never a client constant. Until it loads we fall back to the base
// cap (walk+idle), so the UI never over-promises poses the server would clip.
const BASE_MAX_POSES = 2;
// Each pose is one ~75 s Wan I2V generation (SPEC_MOTION_PROFILES §8). A rough
// "N poses ≈ M min" hint so the GPU cost is visible before the user commits.
const SECONDS_PER_POSE = 75;

function timeHint(n: number): string {
  const mins = (n * SECONDS_PER_POSE) / 60;
  const rounded = Math.round(mins * 2) / 2; // nearest half-minute
  const label = Number.isInteger(rounded) ? `${rounded}` : `${Math.floor(rounded)}½`;
  return `${n} pose${n === 1 ? "" : "s"} ≈ ${label} min`;
}

// The credit price for this many total poses at the caller's tier (§5.2):
// base_design_cost + extra_poses × price_per_extra_pose, where extra = total-2
// (walk+idle are always included). null base cost → show only the time hint.
function priceHint(totalPoses: number, ent: Entitlement | null): string | null {
  if (!ent || ent.base_design_cost == null) return null;
  const extra = Math.max(0, totalPoses - BASE_MAX_POSES);
  const credits = ent.base_design_cost + extra * ent.price_per_extra_pose;
  return `${credits} credits`;
}

// A catalog base option: a breed plus which animal it belongs to (so a flat
// cross-animal list on the General page carries the animal per entry, and a
// themed page's single-animal list just repeats its own animal).
export interface CatalogBaseOption extends CatalogBreed {
  animal: string;         // the animal key this breed belongs to
  animalLabel?: string;   // for grouping/labeling in a flat list
}

// The base source (§3.1). "house" = redesign a house pet; "catalog" = curated
// catalog bases as the img2img source. Themed pages pass one animal's breeds;
// the General page passes ALL animals' bases flattened (each option carries its
// own animal). Either way the SELECTED option's animal drives the build.
export type DesignerBase =
  | { kind: "house" }
  | { kind: "catalog"; options: CatalogBaseOption[]; motionProfile?: string | null };

interface Props {
  base?: DesignerBase;
}

export default function PetDesigner({ base = { kind: "house" } }: Props) {
  // --- house base state (General) ---
  const [housePets, setHousePets] = useState<PetSummary[]>([]);
  const [basePetId, setBasePetId] = useState<string>("");
  // --- catalog base state. Two cascading selectors: species (animal) then breed.
  //     A themed page passes one animal; General passes all. Tracking the species
  //     explicitly (not deriving it from the breed) keeps two species that share a
  //     breed key distinct. ---
  const catalogOptions = base.kind === "catalog" ? base.options : [];
  // Distinct species in the option list, in first-seen order (for the species dropdown).
  const speciesList = catalogOptions.reduce<{ key: string; label: string }[]>((acc, o) => {
    if (!acc.some((s) => s.key === o.animal)) acc.push({ key: o.animal, label: o.animalLabel ?? o.animal });
    return acc;
  }, []);
  const [speciesKey, setSpeciesKey] = useState<string>(catalogOptions[0]?.animal ?? "");
  // Breeds available for the chosen species.
  const breedsForSpecies = catalogOptions.filter((o) => o.animal === speciesKey);
  const [breedKey, setBreedKey] = useState<string>(catalogOptions[0]?.key ?? "");
  const currentAnimal = speciesKey;
  const currentOption = breedsForSpecies.find((o) => o.key === breedKey) ?? null;

  // Selecting a species resets the breed to that species' first breed (so the
  // breed dropdown never shows a breed from the wrong species).
  function selectSpecies(sp: string) {
    setSpeciesKey(sp);
    const first = catalogOptions.find((o) => o.animal === sp);
    if (first) setBreedKey(first.key);
  }
  // --- shared design controls ---
  const [color, setColor] = useState<string>("");          // "" = keep natural
  const [accessories, setAccessories] = useState<string[]>([]);
  const [strength, setStrength] = useState<number>(0.85);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  // Motion menu for the current base's species/profile, and the user's pose picks.
  // Required poses (walk+idle) are always built; `selectedPoses` holds only the
  // OPTIONAL poses the user checked. Keyed off the resolved profile (§4).
  const [motions, setMotions] = useState<MotionMenu | null>(null);
  const [selectedPoses, setSelectedPoses] = useState<Set<string>>(new Set());
  // The caller's resolved tier entitlement (§5.3): caps the pose selector and
  // prices the build. Fetched once; base cap until it loads.
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const { job, error, setError, submit, reset, busy, done } = usePetJob();

  // A preview only matches the controls it was rendered from — any change
  // invalidates it so "Create my design" never builds a stale look.
  useEffect(() => {
    setPreviewId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basePetId, breedKey, color, accessories.join(","), strength]);

  // The pose menu is a projection of the resolved motion profile (§4). Two
  // sources: a house pet resolves by its species name (keyword path); a catalog
  // breed uses its PINNED profile key (the curated path, §4.2). Either way,
  // refetch when the base changes and clear optional picks so a stale selection
  // can't carry across species.
  const basePetName = housePets.find((p) => p.id === basePetId)?.display_name;
  const catalogProfile =
    base.kind === "catalog"
      ? (currentOption?.motion_profile ?? base.motionProfile ?? null)
      : null;
  useEffect(() => {
    const menuKey = base.kind === "catalog" ? catalogProfile : basePetName;
    if (!menuKey) {
      setMotions(null);
      return;
    }
    let cancelled = false;
    const req =
      base.kind === "catalog"
        ? fetchMotions("", menuKey)   // pinned path — themed
        : fetchMotions(menuKey);      // keyword path — General
    req
      .then((m) => {
        if (cancelled) return;
        setMotions(m);
        setSelectedPoses(new Set()); // reset optional picks on species change
      })
      .catch(() => {
        if (!cancelled) setMotions(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basePetName, catalogProfile, base.kind]);

  // Fetch the caller's tier entitlement once — it caps the pose selector (§8.6).
  useEffect(() => {
    fetchEntitlement().then(setEntitlement).catch(() => setEntitlement(null));
  }, []);

  // The pose cap is the resolved entitlement's max_poses; base cap until loaded.
  const maxPoses = entitlement?.max_poses ?? BASE_MAX_POSES;
  // The optional poses (everything the menu offers that isn't required).
  const optionalPoses = (motions?.poses ?? []).filter((p) => !p.required);
  // Total poses this build would generate = required (walk+idle) + user's picks.
  const requiredCount = (motions?.poses ?? []).filter((p) => p.required).length || 2;
  const totalPoses = requiredCount + selectedPoses.size;
  const atCap = totalPoses >= maxPoses;

  function togglePose(name: string) {
    setSelectedPoses((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else if (requiredCount + next.size < maxPoses) {
        next.add(name);
      }
      return next;
    });
  }

  // If the entitlement loads/changes to a smaller cap than the current picks,
  // trim the selection so the UI can never present an over-cap set the server
  // would clip. (E.g. a stale plus selection when the resolved tier is base.)
  useEffect(() => {
    setSelectedPoses((prev) => {
      if (requiredCount + prev.size <= maxPoses) return prev;
      const trimmed = new Set<string>();
      for (const name of Array.from(prev)) {
        if (requiredCount + trimmed.size >= maxPoses) break;
        trimmed.add(name);
      }
      return trimmed;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxPoses, requiredCount]);

  // Whether a base is chosen yet (a house pet is selected, or a catalog breed).
  const hasBase = base.kind === "catalog" ? Boolean(breedKey) : Boolean(basePetId);

  // The FormData fields that identify the base source — the ONE place house vs.
  // catalog diverges in what the request carries. Everything else is shared.
  function appendBaseFields(fd: FormData) {
    if (base.kind === "catalog") {
      fd.append("catalog_animal", currentAnimal);
      fd.append("catalog_breed", breedKey);
    } else {
      fd.append("base_pet_id", basePetId);
    }
  }

  async function makePreview() {
    if (!hasBase || (!color && accessories.length === 0)) {
      setError("Pick a color or at least one accessory first.");
      return;
    }
    setError("");
    setPreviewLoading(true);
    try {
      const fd = new FormData();
      appendBaseFields(fd);
      fd.append("strength", String(strength));
      if (color) fd.append("color", color);
      if (accessories.length) fd.append("accessories", accessories.join(","));
      const { preview_id } = await previewDesign(fd);
      setPreviewId(preview_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  }

  // Load the house roster (house base only); honor /design/general?base=<pet_id>
  // deep links from the pet house's per-card Design buttons.
  useEffect(() => {
    if (base.kind !== "house") return;
    listPets()
      .then((pets) => {
        setHousePets(pets);
        const baseId = new URLSearchParams(window.location.search).get("base");
        if (baseId && pets.some((p) => p.id === baseId)) setBasePetId(baseId);
        else if (pets.length > 0) setBasePetId(pets[0].id);
      })
      .catch(() => setError("Could not load the pet house."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addAccessory(acc: string) {
    if (!acc || accessories.includes(acc) || accessories.length >= MAX_ACCESSORIES) return;
    setAccessories([...accessories, acc]);
  }

  function onSubmit() {
    if (!hasBase) {
      setError(base.kind === "catalog" ? "Pick a breed to design." : "Pick a pet to redesign.");
      return;
    }
    if (!color && accessories.length === 0) {
      setError("Pick a color or at least one accessory.");
      return;
    }
    const fd = new FormData();
    appendBaseFields(fd);
    fd.append("strength", String(strength));
    if (color) fd.append("color", color);
    if (accessories.length) fd.append("accessories", accessories.join(","));
    // If the current design was previewed, the pipeline animates that exact
    // still — what you saw is what you get.
    if (previewId) fd.append("preview_id", previewId);
    // Which poses to generate (§4.3): required poses (walk+idle) are always true;
    // add the optional ones the user checked. Absent → backend default (walk+idle).
    if (selectedPoses.size > 0) {
      const pkg: Record<string, boolean> = {};
      for (const p of motions?.poses ?? []) {
        if (p.required) pkg[p.name] = true;
      }
      Array.from(selectedPoses).forEach((name) => {
        pkg[name] = true;
      });
      fd.append("poses", JSON.stringify(pkg));
    }
    submit(fd);
  }

  function onReset() {
    reset();
    setColor("");
    setAccessories([]);
    setPreviewId(null);
    setSelectedPoses(new Set());
  }

  const basePet = housePets.find((p) => p.id === basePetId);
  // The base thumbnail to show as "original" — a house pet's stored sprite, or
  // the catalog breed's curated base.png.
  const baseThumb =
    base.kind === "catalog" && breedKey && currentAnimal ? (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={catalogBaseImageUrl(currentAnimal, breedKey)}
        alt={`${breedKey} base`}
        style={{ width: 160, height: 160, objectFit: "contain" }}
      />
    ) : basePet ? (
      <PetThumbnail key={`orig-${basePet.id}`} petId={basePet.id} size={160} />
    ) : null;

  // In house mode with an empty house, there's nothing to redesign.
  const houseEmpty = base.kind === "house" && housePets.length === 0;

  return (
    <>
      {!done && (
        <div className="card mb-6 p-6">
          {houseEmpty ? (
            <p className="text-sm" style={{ color: "var(--faint)" }}>
              The house is empty — <Link href="/make" className="underline">make a pet first</Link>, then design on top of it.
            </p>
          ) : (
            <>
              {base.kind === "catalog" ? (
                <>
                  <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                    1. Species &amp; breed
                  </label>
                  <div className="mb-5 flex flex-wrap items-center gap-4">
                    <div className="flex flex-wrap gap-2">
                      {/* Species dropdown — shown when the list spans >1 animal (General).
                          A themed page has one species, so it's hidden there. */}
                      {speciesList.length > 1 && (
                        <select
                          value={speciesKey}
                          onChange={(e) => selectSpecies(e.target.value)}
                          disabled={busy}
                          className="rounded-lg px-3 py-2.5 text-[15px] outline-none"
                          style={{ background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" }}
                        >
                          {speciesList.map((s) => (
                            <option key={s.key} value={s.key}>{s.label}</option>
                          ))}
                        </select>
                      )}
                      {/* Breed dropdown — the breeds for the chosen species. */}
                      <select
                        value={breedKey}
                        onChange={(e) => setBreedKey(e.target.value)}
                        disabled={busy}
                        className="rounded-lg px-3 py-2.5 text-[15px] outline-none"
                        style={{ background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" }}
                      >
                        {breedsForSpecies.map((o) => (
                          <option key={o.key} value={o.key}>{o.label}</option>
                        ))}
                      </select>
                    </div>
                    {breedKey && currentAnimal && (
                      <div className="card shrink-0 p-2">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={catalogBaseImageUrl(currentAnimal, breedKey)}
                          alt={`${breedKey} base`}
                          style={{ width: 64, height: 64, objectFit: "contain" }}
                        />
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                    1. Pet to redesign
                  </label>
                  <div className="mb-5 flex items-center gap-4">
                    <select
                      value={basePetId}
                      onChange={(e) => setBasePetId(e.target.value)}
                      disabled={busy}
                      className="w-full max-w-xs rounded-lg px-3 py-2.5 text-[15px] outline-none"
                      style={{ background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" }}
                    >
                      {housePets.map((p) => (
                        <option key={p.id} value={p.id}>{p.display_name}</option>
                      ))}
                    </select>
                    {basePet && (
                      <div className="card shrink-0 p-2">
                        <PetThumbnail key={basePet.id} petId={basePet.id} size={64} />
                      </div>
                    )}
                  </div>
                </>
              )}

              <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                2. Color ({color || "keep natural"})
              </label>
              <div className="mb-5 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setColor("")}
                  disabled={busy}
                  className="rounded-lg border px-3 py-1.5 text-xs font-medium"
                  style={
                    color === ""
                      ? { background: "rgba(99,102,241,0.15)", color: "var(--heading)", borderColor: "var(--accent)" }
                      : { background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }
                  }
                >
                  natural
                </button>
                {COLORS.map((c) => (
                  <button
                    key={c.name}
                    type="button"
                    title={c.name}
                    onClick={() => setColor(c.name)}
                    disabled={busy}
                    className="h-8 w-8 rounded-full border-2 transition"
                    style={{
                      background: c.css,
                      borderColor: color === c.name ? "#ffffff" : "var(--line)",
                      transform: color === c.name ? "scale(1.15)" : "none",
                    }}
                  />
                ))}
              </div>

              <label className="mono mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                3. Accessories ({accessories.length}/{MAX_ACCESSORIES})
              </label>
              <select
                value=""
                onChange={(e) => addAccessory(e.target.value)}
                disabled={busy || accessories.length >= MAX_ACCESSORIES}
                className="w-full max-w-xs rounded-lg px-3 py-2.5 text-[15px] outline-none"
                style={{ background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" }}
              >
                <option value="">
                  {accessories.length >= MAX_ACCESSORIES ? "max 3 accessories" : "add an accessory…"}
                </option>
                {ACCESSORIES.filter((a) => !accessories.includes(a)).map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
              {accessories.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {accessories.map((a) => (
                    <button
                      key={a}
                      type="button"
                      onClick={() => setAccessories(accessories.filter((x) => x !== a))}
                      disabled={busy}
                      className="rounded-full border px-3 py-1 text-xs font-medium"
                      style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
                    >
                      {a} ✕
                    </button>
                  ))}
                </div>
              )}

              <label className="mono mb-1 mt-5 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                4. How different should it be?
              </label>
              <div className="mb-2 flex gap-2">
                {STRENGTHS.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => setStrength(s.value)}
                    disabled={busy}
                    className="flex-1 rounded-lg border px-3 py-2.5 text-sm font-medium transition"
                    style={
                      strength === s.value
                        ? { background: "rgba(99,102,241,0.15)", color: "var(--heading)", borderColor: "var(--accent)" }
                        : { background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }
                    }
                  >
                    {s.label}
                    <span className="ml-1 text-xs" style={{ color: "var(--faint)" }}>({s.hint})</span>
                  </button>
                ))}
              </div>

              <label className="mono mb-1 mt-5 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                5. Poses to generate{motions ? ` (${totalPoses}/${maxPoses})` : ""}
                {entitlement && entitlement.tier !== "plus" ? (
                  <span className="ml-2" style={{ color: "var(--gold)" }}>· {entitlement.label} plan</span>
                ) : null}
              </label>
              {optionalPoses.length === 0 ? (
                <div className="mono text-xs" style={{ color: "var(--faint)" }}>
                  Walk and idle are always included. This pet has no extra poses to add.
                </div>
              ) : (
                <>
                  <div className="mb-1.5 flex flex-wrap gap-2">
                    {/* Required poses: always on, locked. */}
                    {(motions?.poses ?? [])
                      .filter((p) => p.required)
                      .map((p) => (
                        <span
                          key={p.name}
                          className="rounded-lg border px-3 py-1.5 text-xs font-medium capitalize"
                          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
                          title="always included"
                        >
                          {p.name} ✓
                        </span>
                      ))}
                    {/* Optional poses: the user's choice, up to the cap. */}
                    {optionalPoses.map((p) => {
                      const on = selectedPoses.has(p.name);
                      const lockedByCap = !on && atCap;
                      return (
                        <button
                          key={p.name}
                          type="button"
                          onClick={() => togglePose(p.name)}
                          disabled={busy || lockedByCap}
                          className="rounded-lg border px-3 py-1.5 text-xs font-medium capitalize transition disabled:opacity-45"
                          style={
                            on
                              ? { background: "rgba(99,102,241,0.15)", color: "var(--heading)", borderColor: "var(--accent)" }
                              : { background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }
                          }
                          title={lockedByCap ? "pose limit reached" : undefined}
                        >
                          {on ? "✓ " : ""}{p.name}
                        </button>
                      );
                    })}
                  </div>
                  <div className="mono text-xs" style={{ color: atCap ? "var(--orange)" : "var(--faint)" }}>
                    {timeHint(totalPoses)}
                    {priceHint(totalPoses, entitlement) ? ` · ${priceHint(totalPoses, entitlement)}` : ""}
                    {atCap
                      ? (entitlement?.upsell
                          ? ` · ${entitlement.upsell}`
                          : " · pose limit reached")
                      : ""}
                  </div>
                </>
              )}

              <label className="mono mb-1 mt-5 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
                6. Preview (optional — ~10 seconds; the final pet is built from the exact image you approve)
              </label>
              <div className="flex flex-wrap items-stretch gap-4">
                <div className="card p-3 text-center">
                  {baseThumb}
                  <div className="mono mt-1 text-xs" style={{ color: "var(--faint)" }}>original</div>
                </div>
                <div
                  className="card flex min-w-[186px] flex-col items-center justify-center p-3 text-center"
                  style={previewId ? { borderColor: "rgba(52,211,153,0.5)" } : undefined}
                >
                  {previewId ? (
                    <>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={previewImageUrl(previewId)}
                        alt="design preview"
                        style={{ width: 160, height: 160, objectFit: "contain" }}
                      />
                      <div className="mono mt-1 text-xs" style={{ color: "var(--green)" }}>
                        your design ✓
                      </div>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={makePreview}
                        disabled={busy || previewLoading}
                        className="mono rounded-lg border px-4 py-2.5 text-sm font-semibold disabled:opacity-45"
                        style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
                      >
                        {previewLoading ? "Redrawing… (~10 s)" : "🔍 Preview this design"}
                      </button>
                      <div className="mono mt-2 max-w-[180px] text-xs" style={{ color: "var(--faint)" }}>
                        {previewLoading ? "the GPU is redrawing the pet" : "see the new look before the 3-minute build"}
                      </div>
                    </>
                  )}
                </div>
              </div>

              <button
                onClick={onSubmit}
                disabled={busy}
                className="mono mt-4 w-full rounded-xl py-3.5 text-[15px] font-bold tracking-wide transition active:scale-[0.98] disabled:opacity-45"
                style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}
              >
                {busy ? "Generating…" : previewId ? "Create my design (from the preview)" : "Create my design"}
              </button>
              <div className="mono mt-3 min-h-5 text-sm" style={{ color: "var(--accent)" }}>{error}</div>
            </>
          )}
        </div>
      )}

      {job && <PetJobResult job={job} onReset={onReset} resetLabel="Design another" />}
    </>
  );
}
