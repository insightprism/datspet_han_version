"use client";

/**
 * Design your own — pick a house pet as the base, choose a color and up to
 * three accessories, and the backend composes the generation prompt from the
 * structured picks (no free-text needed). The redraw keeps the base pet's
 * identity; the strength presets control how far it drifts.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { listPets, previewDesign, previewImageUrl, type PetSummary } from "@/lib/api";
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

export default function DesignPage() {
  const [housePets, setHousePets] = useState<PetSummary[]>([]);
  const [basePetId, setBasePetId] = useState<string>("");
  const [color, setColor] = useState<string>("");          // "" = keep natural
  const [accessories, setAccessories] = useState<string[]>([]);
  const [strength, setStrength] = useState<number>(0.85);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const { job, error, setError, submit, reset, busy, done } = usePetJob();

  // A preview only matches the controls it was rendered from — any change
  // invalidates it so "Create my design" never builds a stale look.
  useEffect(() => {
    setPreviewId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basePetId, color, accessories.join(","), strength]);

  async function makePreview() {
    if (!basePetId || (!color && accessories.length === 0)) {
      setError("Pick a color or at least one accessory first.");
      return;
    }
    setError("");
    setPreviewLoading(true);
    try {
      const fd = new FormData();
      fd.append("base_pet_id", basePetId);
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

  // Load the house roster; honor /design?base=<pet_id> deep links from the
  // pet house's per-card Design buttons.
  useEffect(() => {
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
    if (!basePetId) {
      setError("Pick a pet to redesign.");
      return;
    }
    if (!color && accessories.length === 0) {
      setError("Pick a color or at least one accessory.");
      return;
    }
    const fd = new FormData();
    fd.append("base_pet_id", basePetId);
    fd.append("strength", String(strength));
    if (color) fd.append("color", color);
    if (accessories.length) fd.append("accessories", accessories.join(","));
    // If the current design was previewed, the pipeline animates that exact
    // still — what you saw is what you get.
    if (previewId) fd.append("preview_id", previewId);
    submit(fd);
  }

  function onReset() {
    reset();
    setColor("");
    setAccessories([]);
    setPreviewId(null);
  }

  const basePet = housePets.find((p) => p.id === basePetId);

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Design your own
      </h1>
      <p className="mb-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Start from a pet in the house, pick a new color and some accessories, and it gets
        redrawn to your design — same pet, new look. The prompt is composed for you.
      </p>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
        >
          ← Describe a pet instead
        </Link>
        <Link
          href="/house"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
        >
          🏠 Visit the pet house →
        </Link>
      </div>

      {!done && (
        <div className="card mb-6 p-6">
          {housePets.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--faint)" }}>
              The house is empty — <Link href="/" className="underline">make a pet first</Link>, then design on top of it.
            </p>
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
                5. Preview (optional — ~10 seconds; the final pet is built from the exact image you approve)
              </label>
              <div className="flex flex-wrap items-stretch gap-4">
                <div className="card p-3 text-center">
                  {basePet && <PetThumbnail key={`orig-${basePet.id}`} petId={basePet.id} size={160} />}
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
    </main>
  );
}
