"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  handOffToDatsme,
  deletePet,
  donatePet,
  getDatsmeSession,
  getHouseConfig,
  listMyDonations,
  listPets,
  petZipUrl,
  type DatsmeSession,
  type Donation,
  type HouseConfig,
  type PetSummary,
} from "@/lib/api";
import PetStage from "@/components/PetStage";
import PetThumbnail from "@/components/PetThumbnail";
import ConfirmModal from "@/components/ConfirmModal";
import { HOUSE_NAME } from "@/lib/houseCopy";

// On a phone, showing fewer pets per page is the memory fix that matters: each
// mounted card decodes a sprite sheet and each PetStage actor RETAINS one
// (~16 MB decoded), so a full page of them can crash a mobile tab (iOS caps a
// tab well under a gigabyte). The server page size is the desktop value; a narrow
// viewport clamps to this ceiling. A commented constant, not config — the two
// tunable knobs are the cap and the (desktop) page size; this is just "don't
// mount a desktop-sized page on a phone."
const MOBILE_PAGE_CEILING = 6;

// The house's ownership split: a pet is either already in the caller's DatsMe
// house (`in_datsme`, stamped by the host's post-import ack) or not yet adopted.
// "All" stays first and default so the wandering stage keeps showing everything;
// the tabs are a FILTER over the one list, not separate fetches. The row only
// renders once at least one pet is adopted — a house with nothing adopted has
// nothing to differentiate, and a standalone user should not see DatsMe tabs.
type HouseTab = "all" | "inDatsme" | "notInDatsme";
const HOUSE_TABS: { key: HouseTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "inDatsme", label: "✓ In DatsMe" },
  { key: "notInDatsme", label: "Not adopted yet" },
];

/**
 * My Pet House — the pets you've made, wandering the page. The name is a
 * constant (lib/houseCopy) because it is said on five surfaces and drifted the
 * first time it changed.
 *
 * Paged, and the paging is a MEMORY bound, not a nicety (SPEC house-scaling).
 * The house grows without limit, and every rendered card + PetStage actor holds
 * a decoded sprite sheet, so we mount only ONE page at a time — the card grid AND
 * the wandering stage both get just the current page. The animation loop already
 * pauses when the tab is hidden (useAnimationLoop), so a backgrounded house costs
 * nothing. Page size comes from the server (/api/house), clamped down on mobile.
 *
 * Adopting is a LINK, not an API call (SPEC_DATSPET_HOUSE_ADOPT §0.1). It is now
 * the ONLY way a pet reaches DatsMe: the user selects here — where the pets are
 * visible — and we hand the selection to DatsMe's import page, which pulls from
 * our export, quotes a binding price, and charges against the user's own session.
 * DatsPet holds no credential that can trigger a charge
 * (SPEC_DATSPET_FEDERATED_SESSION §6). That page treats `?items=` as a
 * PRESELECTION, so the picking done here survives the trip. Selection is by id,
 * so it spans pages: a pet picked on page 1 stays picked on page 2.
 */
/** What a donor is told, per row (SPEC_PET_STORE §10.8).
 *
 *  `delivered` names the host's own figure — never a constant, because the
 *  amount is a knob DatsPet does not own and hardcoding "1 social point" would
 *  become a lie the day it changes. When DatsMe declined (capped for the day,
 *  or the reward switched off) the pet was still accepted, so the row says so
 *  and claims no points. */
function donationThanks(d: Donation): string {
  if (d.reward_state === "delivered" && (d.points_awarded ?? 0) > 0) {
    const n = d.points_awarded as number;
    return `— thank you! DatsMe credited you ${n} social point${n === 1 ? "" : "s"}.`;
  }
  if (d.reward_state === "owed") return "— thank you! Your thank-you is on its way.";
  return "— thank you, it is with the store now.";
}

export default function HousePage() {
  const [pets, setPets] = useState<PetSummary[] | null>(null);
  const [house, setHouse] = useState<HouseConfig | null>(null);
  const [session, setSession] = useState<DatsmeSession | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adopting, setAdopting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [petToRemove, setPetToRemove] = useState<PetSummary | null>(null);
  // Donating is FINAL (SPEC_PET_STORE §0.5), so it gets its own confirm rather
  // than sharing Remove's — the two dialogs have to say different things.
  const [petToDonate, setPetToDonate] = useState<PetSummary | null>(null);
  const [donating, setDonating] = useState(false);
  const [donations, setDonations] = useState<Donation[]>([]);
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState<HouseTab>("all");
  const [isNarrow, setIsNarrow] = useState(false);

  const loadHouse = useCallback(() => {
    // Independent — fire together, don't chain.
    listPets()
      .then(setPets)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load pets"));
    getHouseConfig().then(setHouse).catch(() => { /* pager falls back to a default */ });
    getDatsmeSession().then(setSession).catch(() => setSession({ launched: false }));
    // Own rows only, and an anonymous caller gets an empty list rather than an
    // error — a house page should not break because nobody has donated.
    listMyDonations().then(setDonations).catch(() => setDonations([]));
  }, []);

  useEffect(() => { loadHouse(); }, [loadHouse]);

  // bfcache restore. DatsMe's Cancel (and browser-Back after an import) returns
  // here via history.back(), which the browser serves from the back/forward cache:
  // this page is NOT reloaded, it is UNFROZEN with its JS state exactly as it was
  // when we left. So it wakes with `adopting` still true — the Adopt button stuck
  // on "Handing over…", disabled forever — and with pre-departure "✓ In DatsMe"
  // chips that predate an import the user just completed. Reset the in-flight flag
  // and re-fetch so the woken page tells the truth about the present. The fix is
  // to handle being woken, NOT to defeat bfcache — instant Back is the feature.
  // Guard on e.persisted: a plain pageshow also fires on every normal load, and an
  // unguarded handler would double-fetch on first render (loadHouse already ran).
  useEffect(() => {
    function onPageShow(e: PageTransitionEvent) {
      if (!e.persisted) return;
      setAdopting(false);
      loadHouse();
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [loadHouse]);

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
  // Capacity ("N / max pets") always counts the WHOLE house — the tab filter
  // must never make the house look emptier than the cap sees it.
  const total = pets?.length ?? 0;
  const inDatsmeCount = useMemo(
    () => (pets ?? []).filter((p) => p.in_datsme).length,
    [pets],
  );
  const showTabs = inDatsmeCount > 0;
  // If a reload empties the adopted set while a filter tab is active, fall back
  // to "all" by derivation — never leave the user staring at a filter for a
  // distinction that no longer exists.
  const activeTab: HouseTab = showTabs ? tab : "all";
  const tabPets = useMemo(() => {
    const all = pets ?? [];
    if (activeTab === "all") return all;
    return all.filter((p) => (activeTab === "inDatsme" ? p.in_datsme : !p.in_datsme));
  }, [pets, activeTab]);

  const pageCount = Math.max(1, Math.ceil(tabPets.length / pageSize));
  // Clamp rather than store-and-sync: a removal (or a tab switch to a shorter
  // list) can shrink the list under the current page, so the page shown is
  // always derived, never stale.
  const safePage = Math.min(page, pageCount - 1);
  const pagedPets = useMemo(
    () => tabPets.slice(safePage * pageSize, safePage * pageSize + pageSize),
    [tabPets, safePage, pageSize],
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
      // The claim-keep-navigate sequence lives in handOffToDatsme, shared with the
      // post-design Adopt (and the catalog page in SPEC_DATSPET_CATALOG_PURCHASE)
      // so the order — which is the part that is easy to get wrong — is written
      // once. See that helper for why claim precedes keep precedes navigate, and
      // why a cancelled checkout deliberately does NOT unclaim.
      await handOffToDatsme(ids, session);
    } catch (e) {
      setAdopting(false);
      setError(
        e instanceof Error ? e.message : "Could not hand those pets to DatsMe",
      );
    }
  }

  /** Give a pet to the store. It does not come back (§10.5), and the slot
   *  frees at once — which is why the card disappears optimistically here the
   *  same way Remove's does. */
  async function confirmDonate() {
    if (!petToDonate) return;
    const pet = petToDonate;
    setPetToDonate(null);
    setDonating(true);
    setError("");
    try {
      const r = await donatePet(pet.id);
      setPets((cur) => (cur ? cur.filter((p) => p.id !== pet.id) : cur));
      // Re-read rather than push a local row: the thank-you's NUMBER comes
      // from DatsMe, and this is the read that picks it up once it answers.
      listMyDonations().then(setDonations).catch(() => {});
      setNotice(r.thanks);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not donate that pet");
    } finally {
      setDonating(false);
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
        {HOUSE_NAME}
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
      {notice && <div className="mono text-sm" style={{ color: "var(--green)" }}>{notice}</div>}

      {/* Donations (SPEC_PET_STORE §10.8). Nothing here is actionable — no
          restore, no appeal, no verdict — which is the point of the model. The
          NUMBER is the host's, echoed exactly as it reported it; DatsPet never
          computes one and never shows a TOTAL, because a total is a balance and
          balances live on DatsMe (§0.6.1). */}
      {donations.length > 0 && (
        <section className="card mb-4 p-4">
          <h2 className="mb-2 text-sm font-semibold" style={{ color: "var(--heading)" }}>
            Pets you donated
          </h2>
          <ul className="flex flex-col gap-1">
            {donations.map((d) => (
              <li key={d.id} className="mono flex flex-wrap items-baseline gap-2 text-xs"
                  style={{ color: "var(--muted)" }}>
                <span style={{ color: "var(--heading)" }}>{d.display_name}</span>
                <span>{donationThanks(d)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {pets && pets.length === 0 && (
        <div className="card p-8 text-center">
          <p style={{ color: "var(--muted)" }}>No pets yet — the house is empty.</p>
          <div className="mt-4 flex flex-wrap justify-center gap-3">
            <Link
              href="/design/general"
              className="mono inline-block rounded-lg border px-5 py-3 text-sm font-semibold"
              style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
            >
              Design your first pet
            </Link>
            {/* An empty house is exactly where "browse ready-made" belongs — it is
                the moment a new user most wants a pet and least wants to wait three
                minutes for one (SPEC_DATSPET_CATALOG_PURCHASE §2). Secondary
                styling: designing stays the primary flow. */}
            <Link
              href="/catalog"
              className="mono inline-block rounded-lg border px-5 py-3 text-sm font-semibold"
              style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
            >
              Or adopt a ready-made one
            </Link>
          </div>
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
                      house full — remove one to make room, or donate one
                    </span>
                  )}
                </>
              ) : (
                <>{total} pets</>
              )}
            </span>
          </div>

          {showTabs && (
            <div className="mb-3 flex flex-wrap gap-2">
              {HOUSE_TABS.map((t) => {
                const count =
                  t.key === "all"
                    ? total
                    : t.key === "inDatsme"
                      ? inDatsmeCount
                      : total - inDatsmeCount;
                const active = activeTab === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => {
                      setTab(t.key);
                      setPage(0);
                    }}
                    className="rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={
                      active
                        ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                        : { color: "var(--muted)", borderColor: "var(--line)" }
                    }
                  >
                    {t.label} ({count})
                  </button>
                );
              })}
            </div>
          )}

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
                    Select
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
                {/* in_datsme is informational, never a gate: re-importing is free
                    and updates the pet in place — so the badge marks the state
                    without hiding the Select box. Shown even outside a DatsMe
                    launch: adoption survives the session that did it. */}
                {p.in_datsme && (
                  <div
                    className="mono mt-1 inline-block rounded-md border px-2 py-0.5 text-[10px] font-semibold"
                    style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
                  >
                    ✓ In DatsMe
                  </div>
                )}
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
                  {p.donatable && canAdopt && (
                    <button
                      type="button"
                      onClick={() => setPetToDonate(p)}
                      disabled={donating}
                      title="Give this pet to the Pet Store — permanent"
                      className="rounded-md border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85 disabled:opacity-40"
                      style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
                    >
                      🎁 Donate
                    </button>
                  )}
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
        open={petToDonate !== null}
        title={`Donate ${petToDonate?.display_name ?? "this pet"} to the Pet Store?`}
        body={"This is permanent. The pet leaves your house for good and you cannot get it back — like giving something to a charity shop. DatsMe thanks you with social points."}
        confirmLabel="Donate — permanently"
        tone="primary"
        onConfirm={confirmDonate}
        onCancel={() => setPetToDonate(null)}
      />

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
