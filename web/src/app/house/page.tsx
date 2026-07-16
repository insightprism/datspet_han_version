"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  claimPets,
  deletePet,
  getDatsmeSession,
  getHouseConfig,
  listPets,
  petZipUrl,
  type DatsmeSession,
  type HouseConfig,
  type PetSummary,
} from "@/lib/api";
import PetStage from "@/components/PetStage";
import PetThumbnail from "@/components/PetThumbnail";
import ConfirmModal from "@/components/ConfirmModal";

// On a phone, showing fewer pets per page is the memory fix that matters: each
// mounted card decodes a sprite sheet and each PetStage actor RETAINS one
// (~16 MB decoded), so a full page of them can crash a mobile tab (iOS caps a
// tab well under a gigabyte). The server page size is the desktop value; a narrow
// viewport clamps to this ceiling. A commented constant, not config — the two
// tunable knobs are the cap and the (desktop) page size; this is just "don't
// mount a desktop-sized page on a phone."
const MOBILE_PAGE_CEILING = 6;

/**
 * The Pet House — the pets you've made, wandering the page.
 *
 * Paged, and the paging is a MEMORY bound, not a nicety (SPEC house-scaling).
 * The house grows without limit, and every rendered card + PetStage actor holds
 * a decoded sprite sheet, so we mount only ONE page at a time — the card grid AND
 * the wandering stage both get just the current page. The animation loop already
 * pauses when the tab is hidden (useAnimationLoop), so a backgrounded house costs
 * nothing. Page size comes from the server (/api/house), clamped down on mobile.
 *
 * Adopting is a LINK, not an API call (SPEC_DATSPET_HOUSE_ADOPT §0.1). A launch
 * nonce authorizes exactly ONE writeback, so a house of Accept buttons cannot
 * work over the push path at any key or batch size. Instead the user selects
 * here — where the pets are visible — and we hand the selection to DatsMe's
 * import page, which pulls from our export. That page treats `?items=` as a
 * PRESELECTION, so the picking done here survives the trip. Selection is by id,
 * so it spans pages: a pet picked on page 1 stays picked on page 2.
 */
export default function HousePage() {
  const [pets, setPets] = useState<PetSummary[] | null>(null);
  const [house, setHouse] = useState<HouseConfig | null>(null);
  const [session, setSession] = useState<DatsmeSession | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adopting, setAdopting] = useState(false);
  const [error, setError] = useState("");
  const [petToRemove, setPetToRemove] = useState<PetSummary | null>(null);
  const [page, setPage] = useState(0);
  const [isNarrow, setIsNarrow] = useState(false);

  useEffect(() => {
    // Independent — fire together, don't chain.
    listPets()
      .then(setPets)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load pets"));
    getHouseConfig().then(setHouse).catch(() => { /* pager falls back to a default */ });
    getDatsmeSession().then(setSession).catch(() => setSession({ launched: false }));
  }, []);

  // Track a narrow viewport so mobile mounts fewer sheets. matchMedia (not a
  // width guess) so it tracks rotation and resize; read in an effect so the
  // static export doesn't touch window during render.
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const sync = () => setIsNarrow(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  const canAdopt = Boolean(session?.launched && session?.import_url);

  const pageSize = Math.max(
    1,
    isNarrow
      ? Math.min(house?.page_size ?? 10, MOBILE_PAGE_CEILING)
      : house?.page_size ?? 10,
  );
  const total = pets?.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  // Clamp rather than store-and-sync: a removal can shrink the list under the
  // current page, so the page shown is always derived, never stale.
  const safePage = Math.min(page, pageCount - 1);
  const pagedPets = useMemo(
    () => (pets ?? []).slice(safePage * pageSize, safePage * pageSize + pageSize),
    [pets, safePage, pageSize],
  );

  function toggle(petId: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(petId)) next.delete(petId);
      else next.add(petId);
      return next;
    });
  }

  async function adoptSelected() {
    if (!session?.import_url || selected.size === 0) return;
    setError("");
    setAdopting(true);
    const ids = (pets ?? []).filter((p) => selected.has(p.id)).map((p) => p.id);
    try {
      // Claim first, navigate second. An unclaimed pet is visible here but
      // invisible to /partner/export, so handing it over unclaimed lands the user
      // on an import page where it silently isn't listed (§2). Only bother when
      // something actually needs it.
      const needClaim = (pets ?? [])
        .filter((p) => selected.has(p.id) && p.claimable)
        .map((p) => p.id);
      if (needClaim.length > 0) await claimPets(needClaim);
      window.location.href = `${session.import_url}?items=${ids.join(",")}`;
    } catch (e) {
      setAdopting(false);
      setError(
        e instanceof Error ? e.message : "Could not hand those pets to DatsMe",
      );
    }
  }

  async function confirmRemove() {
    if (!petToRemove) return;
    const pet = petToRemove;
    setPetToRemove(null);
    try {
      await deletePet(pet.id);
      setPets((cur) => (cur ? cur.filter((p) => p.id !== pet.id) : cur));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove the pet");
    }
  }

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        The pet house
      </h1>
      <p className="mb-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Every pet made here lives on this page. They wander on their own —
        click anywhere on the page to call one over, or click a pet to get it excited.
      </p>

      <Link
        href="/"
        className="mb-6 inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
        style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
      >
        ← Back to designing
      </Link>

      {error && <div className="mono text-sm" style={{ color: "var(--accent)" }}>{error}</div>}

      {pets && pets.length === 0 && (
        <div className="card p-8 text-center">
          <p style={{ color: "var(--muted)" }}>No pets yet — the house is empty.</p>
          <Link
            href="/design/general"
            className="mono mt-4 inline-block rounded-lg border px-5 py-3 text-sm font-semibold"
            style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
          >
            Design your first pet
          </Link>
        </div>
      )}

      {canAdopt && pets && pets.length > 0 && (
        <div
          className="card mb-4 flex flex-wrap items-center justify-between gap-3 p-3"
          style={{ borderColor: selected.size ? "rgba(52,211,153,0.4)" : undefined }}
        >
          <div className="text-sm" style={{ color: "var(--muted)" }}>
            {selected.size === 0
              ? "Pick the pets you want in your DatsMe house."
              : `${selected.size} pet${selected.size > 1 ? "s" : ""} selected`}
            {/* No price here on purpose. The cost is a function of each pet's pose
                count AND DatsMe's own credit config; anything we render is a guess
                that would disagree with the confirm page. DatsMe quotes, and it
                quotes exactly. */}
            <span className="ml-1" style={{ color: "var(--faint)" }}>
              You&apos;ll see the exact cost on DatsMe before anything is charged.
            </span>
          </div>
          <button
            type="button"
            disabled={selected.size === 0 || adopting}
            onClick={adoptSelected}
            className="rounded-lg border px-4 py-2 text-sm font-semibold transition hover:opacity-85 disabled:opacity-40"
            style={{
              background: "rgba(52,211,153,0.12)",
              color: "var(--green)",
              borderColor: "rgba(52,211,153,0.4)",
            }}
          >
            {adopting
              ? "Handing over…"
              : `✓ Adopt ${selected.size || ""} to DatsMe`.replace("  ", " ")}
          </button>
        </div>
      )}

      {pets && pets.length > 0 && (
        <>
          <div className="mb-3 flex items-center justify-between text-sm" style={{ color: "var(--muted)" }}>
            <span>
              {house ? (
                <>
                  <strong style={{ color: total >= house.max_pets ? "#f87171" : "var(--heading)" }}>
                    {total}
                  </strong>{" "}
                  / {house.max_pets} pets
                  {total >= house.max_pets && (
                    <span className="ml-2" style={{ color: "#f87171" }}>
                      house full — remove one to make room
                    </span>
                  )}
                </>
              ) : (
                <>{total} pets</>
              )}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
            {pagedPets.map((p) => (
              <div
                key={p.id}
                className="card p-4 text-center"
                style={
                  selected.has(p.id)
                    ? { borderColor: "var(--green)", boxShadow: "0 0 0 1px var(--green)" }
                    : undefined
                }
              >
                {canAdopt && (
                  <label className="mb-1 flex cursor-pointer items-center justify-center gap-2 text-xs"
                         style={{ color: "var(--muted)" }}>
                    <input
                      type="checkbox"
                      checked={selected.has(p.id)}
                      onChange={() => toggle(p.id)}
                      style={{ accentColor: "var(--green)" }}
                    />
                    {/* in_datsme is informational, never a gate: re-importing is
                        free and updates the pet in place. */}
                    {p.in_datsme ? "✓ In DatsMe" : "Select"}
                  </label>
                )}
                <div className="mx-auto w-fit">
                  <PetThumbnail petId={p.id} size={88} />
                </div>
                <div className="mt-2 truncate text-sm" style={{ color: "var(--heading)" }}>
                  {p.display_name}
                </div>
                <div className="mono mt-0.5 truncate text-[11px]" style={{ color: "var(--faint)" }}>
                  {p.breed_id}
                </div>
                {/* NO "🎨 Redesign" button. It linked to /design?base=<id> and had never
                    worked in any revision: the landing never read ?base, and after the
                    redesign nothing reads it at all. Rather than ship a third revision of
                    a button that has never once done anything, it is gone.

                    It is not coming back in this shape either, and the reason is the
                    archetype rule (SPEC_PET_DESIGNER_FLOW §2.1): a house pet is somebody's
                    FINISHED design — step 2 has already run on it — so starting there
                    means designing a design, with the modifiers compounding invisibly and
                    no way back to the archetype. Commit 74c1783 removed house pets as a
                    base source deliberately; this button was the last dangling thread of
                    that decision. §3.9 says how it should arrive if it is ever revived:
                    pre-resolved, as an explicit deep link, never a door. */}
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  <a
                    href={petZipUrl(p.id)}
                    download
                    title="Download the DatsMe breed bundle — upload it in DatsMe under Settings → Pet"
                    className="rounded-md border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
                  >
                    ⬇ DatsMe zip
                  </a>
                  <button
                    type="button"
                    onClick={() => setPetToRemove(p)}
                    className="rounded-md border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={{ background: "rgba(239,68,68,0.1)", color: "#f87171", borderColor: "rgba(239,68,68,0.35)" }}
                  >
                    🗑 Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          {pageCount > 1 && (
            <div className="mt-5 flex items-center justify-center gap-4">
              <button
                type="button"
                disabled={safePage <= 0}
                onClick={() => setPage(safePage - 1)}
                className="rounded-lg border px-4 py-2 text-sm font-semibold transition hover:opacity-85 disabled:opacity-40"
                style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
              >
                ← Prev
              </button>
              <span className="mono text-sm" style={{ color: "var(--muted)" }}>
                Page {safePage + 1} of {pageCount}
              </span>
              <button
                type="button"
                disabled={safePage >= pageCount - 1}
                onClick={() => setPage(safePage + 1)}
                className="rounded-lg border px-4 py-2 text-sm font-semibold transition hover:opacity-85 disabled:opacity-40"
                style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
              >
                Next →
              </button>
            </div>
          )}

          {/* Only THIS page's pets are alive — mounting all of them is the memory
              blowout we're avoiding. Fixed to the viewport floor by the engine. */}
          <PetStage pets={pagedPets.map((p) => ({ id: p.id, display_name: p.display_name }))} />
        </>
      )}

      <ConfirmModal
        open={petToRemove !== null}
        title={`Remove ${petToRemove?.display_name ?? "this pet"}?`}
        body="It disappears from the house and its bundle is deleted from this machine. This can't be undone (though you can always generate a similar one)."
        confirmLabel="Remove pet"
        onConfirm={confirmRemove}
        onCancel={() => setPetToRemove(null)}
      />
    </main>
  );
}
