"use client";

/**
 * /catalog — The Pet Store (SPEC_PET_STORE §6.1).
 *
 * The URL stays /catalog (both entry points already link here; a URL is an
 * address, not a name); the page is the DB-backed store that replaced the
 * file-sample grid (§8). Search + filters run CLIENT-SIDE over the one
 * cacheable listing (storeFilter.ts — the ~200-row tripwire lives there).
 *
 * Still the second entrance to ONE checkout. Adopting copies a store bundle
 * into your house as a draft (zero GPU, instant); the money happens afterwards
 * on the host, through the same `handOffToDatsme` the designer and the house
 * use. Nothing here prices anything — no number, and no cheaper-than-designing
 * claim either: the relation between the two prices is a host knob (§0.2) that
 * can change under the page. If this file ever computes a price, §0.5.1's
 * tripwire has fired.
 *
 * ADOPT FIRST, THEN SIGN IN (unchanged from the catalog-purchase spec §0.4).
 * The adopt lands under the visitor's per-browser anonymous owner id, the pet
 * id rides the sign-in bounce in `?adopted=`, and claim-at-launch binds it to
 * their DatsMe user on the way back. The branch tests `session.launched`, NOT
 * `import_url` — `import_url` exists while signed out, and branching on it
 * would send an anonymous visitor into handOffToDatsme, where claimPets 401s.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  adoptStorePet,
  datsmeSignInUrlForHere,
  fetchStoreListings,
  getDatsmeSession,
  fetchEntitlement,
  handOffToDatsme,
  storePreviewUrl,
  type DatsmeSession,
  type Entitlement,
  type StoreListing,
} from "@/lib/api";
import { animalsPresent, filterListings, NO_FILTER, type StoreFilter } from "./storeFilter";

/** Carries an adopted pet across the sign-in bounce, so the hand-off can resume
 *  on the way back. Same idea as the designer's `?job=`. */
const ADOPTED_PARAM = "adopted";

export default function PetStorePage() {
  const [listings, setListings] = useState<StoreListing[] | null>(null);
  const [session, setSession] = useState<DatsmeSession | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [filter, setFilter] = useState<StoreFilter>(NO_FILTER);
  const [busy, setBusy] = useState<string | null>(null);   // store pet id
  const [error, setError] = useState("");

  useEffect(() => {
    fetchStoreListings().then(setListings).catch(() =>
      setError("Could not load the pet store"));
    fetchEntitlement().then(setEntitlement).catch(() => setEntitlement(null));
  }, []);

  // Resume an adopt that was interrupted by the sign-in bounce. Runs once the
  // session is known and only when it is LIVE — arriving still signed out means
  // the user declined at the host, and the pet simply waits in their house.
  const resumeAfterSignIn = useCallback((s: DatsmeSession) => {
    const petId = new URLSearchParams(window.location.search).get(ADOPTED_PARAM);
    if (!petId || !s.launched) return;
    // Strip it first: a reload must not fire the hand-off twice.
    const url = new URL(window.location.href);
    url.searchParams.delete(ADOPTED_PARAM);
    window.history.replaceState(null, "", url.toString());
    handOffToDatsme([petId], s).catch((e) =>
      setError(e instanceof Error ? e.message : "Could not hand that pet to DatsMe"));
  }, []);

  useEffect(() => {
    getDatsmeSession()
      .then((s) => { setSession(s); resumeAfterSignIn(s); })
      .catch(() => setSession({ launched: false }));
  }, [resumeAfterSignIn]);

  async function adopt(storeId: string) {
    setError("");
    setBusy(storeId);
    try {
      const { pet_id } = await adoptStorePet(storeId);
      if (!session?.launched) {
        // Adopt first, sign in second. The pet is already safely theirs under the
        // anonymous owner; the bounce returns here and the resume finishes it.
        const url = new URL(window.location.href);
        url.searchParams.set(ADOPTED_PARAM, pet_id);
        window.history.replaceState(null, "", url.toString());
        const signin = datsmeSignInUrlForHere(session ?? { launched: false });
        if (signin) { window.location.href = signin; return; }
      }
      if (session) await handOffToDatsme([pet_id], session);
    } catch (e) {
      setBusy(null);
      setError(e instanceof Error ? e.message : "Could not adopt this pet");
    }
  }

  // Tier data decides, never a branch in this page — and since SPEC_PET_STORE §9
  // the server enforces it too; this only spares the user a doomed click.
  const canAdopt = entitlement ? entitlement.can_adopt_samples !== false : true;
  const animals = animalsPresent(listings ?? []);
  const shown = filterListings(listings ?? [], filter);
  const filtering = filter !== NO_FILTER &&
    (filter.query.trim() !== "" || filter.animal !== null || filter.tag !== null);

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        The Pet Store
      </h1>
      <p className="mb-6 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Ready-made pets, adoptable right away — no waiting for a build. You&apos;ll
        see the exact cost on DatsMe before anything is charged. Or{" "}
        <Link href="/design/general" style={{ color: "var(--accent)" }}>
          design your own
        </Link>{" "}
        if you want something that is exactly yours.
      </p>

      {error && (
        <div className="mono mb-4 text-sm" style={{ color: "var(--accent)" }}>{error}</div>
      )}

      {listings === null && (
        <div className="mono text-sm" style={{ color: "var(--faint)" }}>Loading…</div>
      )}

      {listings !== null && listings.length === 0 && (
        // Not an error: the shelf can legitimately be empty while stock is built up.
        <div className="card p-4">
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No ready-made pets yet.{" "}
            <Link href="/design/general" style={{ color: "var(--accent)" }}>
              Design one instead
            </Link>{" "}
            — it takes about three minutes.
          </p>
        </div>
      )}

      {listings !== null && listings.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <input
              className="input max-w-xs"
              type="search"
              placeholder="Search pets, colors, moods…"
              value={filter.query}
              onChange={(e) => setFilter((f) => ({ ...f, query: e.target.value }))}
            />
            {animals.length > 1 && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setFilter((f) => ({ ...f, animal: null }))}
                  className="rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                  style={filter.animal === null
                    ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                    : { color: "var(--muted)", borderColor: "var(--line)" }}
                >
                  All
                </button>
                {animals.map((animal) => (
                  <button
                    key={animal}
                    type="button"
                    onClick={() => setFilter((f) => ({
                      ...f, animal: f.animal === animal ? null : animal,
                    }))}
                    className="rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={filter.animal === animal
                      ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                      : { color: "var(--muted)", borderColor: "var(--line)" }}
                  >
                    {animal}
                  </button>
                ))}
              </div>
            )}
            {filter.tag && (
              <button
                type="button"
                onClick={() => setFilter((f) => ({ ...f, tag: null }))}
                className="mono rounded-lg border px-3 py-1.5 text-xs transition hover:opacity-85"
                style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
              >
                #{filter.tag} ✕
              </button>
            )}
          </div>

          {shown.length === 0 && filtering && (
            <p className="mono text-sm" style={{ color: "var(--faint)" }}>
              Nothing on the shelf matches — try clearing a filter.
            </p>
          )}

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {shown.map((pet) => (
              <figure key={pet.id} className="card m-0 flex flex-col gap-2 p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={storePreviewUrl(pet.id)}
                  alt={`${pet.display_name} — a ready-made ${pet.animal}`}
                  style={{ width: "100%", aspectRatio: "1", objectFit: "contain" }}
                />
                <figcaption className="flex flex-col gap-1">
                  <span className="text-sm font-semibold" style={{ color: "var(--heading)" }}>
                    {pet.display_name}
                  </span>
                  <span className="mono text-[11px]" style={{ color: "var(--faint)" }}>
                    {pet.animal} · {pet.pose_count} pose{pet.pose_count === 1 ? "" : "s"}
                  </span>
                  {pet.description && (
                    <span className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                      {pet.description}
                    </span>
                  )}
                  {pet.tags.length > 0 && (
                    <span className="flex flex-wrap gap-1">
                      {pet.tags.map((tag) => (
                        <button
                          key={tag}
                          type="button"
                          onClick={() => setFilter((f) => ({
                            ...f, tag: f.tag === tag ? null : tag,
                          }))}
                          className="mono rounded border px-1.5 py-0.5 text-[10px] transition hover:opacity-85"
                          style={filter.tag === tag
                            ? { color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }
                            : { color: "var(--faint)", borderColor: "var(--line)" }}
                        >
                          #{tag}
                        </button>
                      ))}
                    </span>
                  )}
                </figcaption>
                {canAdopt && (
                  <button
                    onClick={() => adopt(pet.id)}
                    disabled={busy !== null}
                    className="mono mt-auto rounded-lg border px-3 py-2 text-sm font-bold disabled:opacity-70"
                    style={{
                      background: "linear-gradient(135deg, #10b981, #059669)",
                      color: "var(--heading)", borderColor: "transparent",
                    }}
                  >
                    {busy === pet.id ? "Adopting…" : "Adopt this one"}
                  </button>
                )}
              </figure>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
