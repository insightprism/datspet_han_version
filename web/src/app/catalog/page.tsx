"use client";

/**
 * /catalog — browse ready-made pets and buy one (SPEC_DATSPET_CATALOG_PURCHASE).
 *
 * The second entrance to ONE checkout. Adopting copies a curated bundle into your
 * house as a draft (zero GPU, instant); the money happens afterwards on the host,
 * through the same `handOffToDatsme` the designer and the house use. Nothing here
 * prices anything — if this file ever computes a number, §0.3's tripwire has fired.
 *
 * ADOPT FIRST, THEN SIGN IN. The point of the page is that a visitor can commit to
 * a pet before they have an account: the adopt lands under their per-browser
 * anonymous owner id, and claim-at-launch binds it to their DatsMe user on the way
 * back. So the page owns a short branch the shared helper deliberately does not
 * have (§0.4).
 *
 * The branch tests `session.launched`, NOT `session.import_url`. `import_url` is
 * built whenever the backend is integrated and is present while signed out, so
 * branching on it would send an anonymous visitor into handOffToDatsme, where
 * claimPets 401s and throws — the exact path this page exists to support.
 *
 * The pet id rides the sign-in bounce in `?adopted=`, which is the designer's
 * `?job=` pattern rather than a new one: `currentReturnPath` carries path AND
 * query so "sign in and come back" cannot drop work in flight.
 *
 * This does NOT reuse <BaseGalleryDialog>. That renders BREEDS (`base_image_url`)
 * for step 1 of the designer, not samples (`preview_url`), and its own docstring
 * forbids making it multi-purpose. What is shared is the READER — one
 * `fetchCatalog()`, one shape — which is what actually keeps the two from drifting.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  adoptSample,
  catalogSamplePreviewUrl,
  datsmeSignInUrlForHere,
  fetchCatalog,
  getDatsmeSession,
  fetchEntitlement,
  handOffToDatsme,
  type CatalogAnimal,
  type DatsmeSession,
  type Entitlement,
} from "@/lib/api";

/** Carries an adopted pet across the sign-in bounce, so the hand-off can resume
 *  on the way back. Same idea as the designer's `?job=`. */
const ADOPTED_PARAM = "adopted";

export default function CatalogPage() {
  const [animals, setAnimals] = useState<CatalogAnimal[] | null>(null);
  const [session, setSession] = useState<DatsmeSession | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [busy, setBusy] = useState<string | null>(null);   // `${animal}/${sample}`
  const [error, setError] = useState("");

  useEffect(() => {
    fetchCatalog().then(setAnimals).catch(() =>
      setError("Could not load the catalog"));
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

  async function adopt(animal: string, sample: string) {
    setError("");
    setBusy(`${animal}/${sample}`);
    try {
      const { pet_id } = await adoptSample(animal, sample);
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

  // Tier data decides, never a branch in this page. Today no tier sets it false
  // (SPEC_DATSPET_CATALOG_PURCHASE §0.6), and note the gate is advisory — the
  // endpoint does not enforce it, so this hides an action rather than securing one.
  const canAdopt = entitlement ? entitlement.can_adopt_samples !== false : true;
  const withSamples = (animals ?? []).filter((a) => a.samples.length > 0);

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Ready-made pets
      </h1>
      <p className="mb-6 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Pets we already built, ready to adopt right now — no waiting for a build.
        Or{" "}
        <Link href="/design/general" style={{ color: "var(--accent)" }}>
          design your own
        </Link>{" "}
        if you want something that is exactly yours.
      </p>

      {error && (
        <div className="mono mb-4 text-sm" style={{ color: "var(--accent)" }}>{error}</div>
      )}

      {animals === null && (
        <div className="mono text-sm" style={{ color: "var(--faint)" }}>Loading…</div>
      )}

      {animals !== null && withSamples.length === 0 && (
        // Not an error: an animal with no curated samples simply offers none, and
        // the catalog can legitimately be empty while sample content is built up.
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

      {withSamples.map((animal) => (
        <section key={animal.key} className="mb-8">
          <h2 className="mb-3 text-xl" style={{ color: "var(--heading)" }}>
            {animal.label}
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {animal.samples.map((sample) => {
              const id = `${animal.key}/${sample.key}`;
              return (
                <figure key={sample.key} className="card m-0 flex flex-col gap-2 p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={catalogSamplePreviewUrl(animal.key, sample.key)}
                    alt={`a ready-made ${animal.label.toLowerCase()}`}
                    style={{ width: "100%", aspectRatio: "1", objectFit: "contain" }}
                  />
                  <figcaption className="mono text-xs" style={{ color: "var(--muted)" }}>
                    {sample.key}
                  </figcaption>
                  {canAdopt && (
                    <button
                      onClick={() => adopt(animal.key, sample.key)}
                      disabled={busy !== null}
                      className="mono rounded-lg border px-3 py-2 text-sm font-bold disabled:opacity-70"
                      style={{
                        background: "linear-gradient(135deg, #10b981, #059669)",
                        color: "var(--heading)", borderColor: "transparent",
                      }}
                    >
                      {busy === id ? "Adopting…" : "Adopt this one"}
                    </button>
                  )}
                </figure>
              );
            })}
          </div>
        </section>
      ))}
    </main>
  );
}
