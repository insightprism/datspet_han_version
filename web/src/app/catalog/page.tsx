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
  storeManifestUrl,
  storePreviewUrl,
  storeSheetUrl,
  type DatsmeSession,
  type Entitlement,
  type StoreListing,
} from "@/lib/api";
import { animalsPresent, filterListings, NO_FILTER, tagsPresent,
         type StoreFilter } from "./storeFilter";
import ModalOverlay from "@/components/ModalOverlay";
import PosePlayer from "@/components/PosePlayer";

/** Carries an adopted pet across the sign-in bounce, so the hand-off can resume
 *  on the way back. Same idea as the designer's `?job=`. */
const ADOPTED_PARAM = "adopted";

/** How long each pose holds before the tour moves on (§6.4). A pose is 16
 *  frames at 12 fps ≈ 1.33 s, so this is about two full loops — enough to read
 *  the motion, short enough that eight poses stay a ~20 s tour. */
const POSE_DWELL_MS = 2600;

const LISTING_TEXT_LABEL = "Listing text — description and tags (admin)";
const NO_DESCRIPTION = "No description.";
const NO_TAGS = "No tags.";

export default function PetStorePage() {
  const [listings, setListings] = useState<StoreListing[] | null>(null);
  const [session, setSession] = useState<DatsmeSession | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [filter, setFilter] = useState<StoreFilter>(NO_FILTER);
  const [busy, setBusy] = useState<string | null>(null);   // store pet id
  const [error, setError] = useState("");
  // The listing whose text an ADMIN asked to see (§6.1a). Never a fetch: the
  // description and tags are already in the payload every browser receives —
  // that is what makes search work — so this only chooses to render them.
  const [details, setDetails] = useState<StoreListing | null>(null);
  // ONE card animates at a time (§6.4). Each player fetches a multi-megabyte
  // sheet and runs its own rAF loop, so a grid of them would be both heavy and
  // visually unreadable — and "which pet was that" is the question the feature
  // exists to answer. Starting one stops the other.
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [poseIndex, setPoseIndex] = useState(0);

  // The tour: advance through the playing pet's poses, looping. Keyed on the id
  // alone, so the interval is not torn down and rebuilt on every pose change.
  useEffect(() => {
    if (playingId === null) return;
    const poses = listings?.find((p) => p.id === playingId)?.poses ?? [];
    if (poses.length <= 1) return;
    const timer = setInterval(
      () => setPoseIndex((i) => (i + 1) % poses.length), POSE_DWELL_MS);
    return () => clearInterval(timer);
  }, [playingId, listings]);

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
  const tags = tagsPresent(listings ?? []);
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
          </div>

          {/* The tag filter, which used to live on every card. Tags are filter
              vocabulary, not card content — but they were also the only way to
              SET this filter, so they move here rather than disappear (§6.1).
              An active tag stays visible even outside the top slice, otherwise
              a rare tag could not be cleared once chosen. */}
          {tags.length > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {(filter.tag && !tags.includes(filter.tag)
                ? [filter.tag, ...tags] : tags).map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => setFilter((f) => ({
                    ...f, tag: f.tag === tag ? null : tag,
                  }))}
                  className="mono rounded border px-2 py-1 text-[11px] transition hover:opacity-85"
                  style={filter.tag === tag
                    ? { background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }
                    : { color: "var(--faint)", borderColor: "var(--line)" }}
                >
                  #{tag}{filter.tag === tag ? " ✕" : ""}
                </button>
              ))}
            </div>
          )}

          {shown.length === 0 && filtering && (
            <p className="mono text-sm" style={{ color: "var(--faint)" }}>
              Nothing on the shelf matches — try clearing a filter.
            </p>
          )}

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {shown.map((pet) => (
              <figure key={pet.id} className="card relative m-0 flex flex-col gap-2 p-3">
                {/* Admin-only peek at the listing text this card no longer
                    shows (§6.1a). Keyed on `session.admin` — the VERIFIED adm
                    cookie, the "render the admin tools" signal — not on
                    `system_admin`, which only answers "would this user pass the
                    bounce" and is a display hint the host sends unverified. */}
                {session?.admin && (
                  <button
                    type="button"
                    title={LISTING_TEXT_LABEL}
                    aria-label={`${LISTING_TEXT_LABEL} for ${pet.display_name}`}
                    onClick={() => setDetails(pet)}
                    className="mono absolute right-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full border text-[11px] transition hover:opacity-85"
                    style={{ background: "#151515", color: "var(--gold)", borderColor: "var(--line)" }}
                  >
                    ⓘ
                  </button>
                )}
                {playingId === pet.id && pet.poses.length > 0 ? (
                  // The SAME player the result panel and the Motion Lab use, on
                  // its already-existing arbitrary-sheet source shape — not a
                  // second frame-cycling implementation that could disagree
                  // about fps or column count.
                  <PosePlayer
                    source={{ sheetUrl: storeSheetUrl(pet.id),
                              manifestUrl: storeManifestUrl(pet.id) }}
                    pose={pet.poses[poseIndex % pet.poses.length]}
                    fill
                  />
                ) : (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={storePreviewUrl(pet.id)}
                    alt={`${pet.display_name} — a ready-made ${pet.animal}`}
                    style={{ width: "100%", aspectRatio: "1", objectFit: "contain" }}
                  />
                )}
                <figcaption className="flex flex-col gap-1">
                  <span className="text-sm font-semibold" style={{ color: "var(--heading)" }}>
                    {pet.display_name}
                  </span>
                  <span className="mono text-[11px]" style={{ color: "var(--faint)" }}>
                    {pet.animal}
                  </span>
                  {/* WHAT it can do, not how many things it can do (§6.1). The
                      count was the one fact a shopper could not act on: "8
                      poses" does not say whether it flies. Description and tags
                      are gone from the card entirely — the picture says what
                      the pet is, and both remain searchable and, for tags,
                      filterable from the bar above. */}
                  {pet.poses.length > 0 && (
                    <span className="flex flex-wrap gap-1">
                      {pet.poses.map((pose, i) => {
                        // While the tour runs, the chip list doubles as its
                        // progress readout — you can see WHICH pose you are
                        // watching, which is the whole point of naming them.
                        const live = playingId === pet.id
                          && i === poseIndex % pet.poses.length;
                        return (
                          <span
                            key={pose}
                            className="mono rounded border px-1.5 py-0.5 text-[10px]"
                            style={live
                              ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                              : { color: "var(--muted)", borderColor: "var(--line)" }}
                          >
                            {pose}
                          </span>
                        );
                      })}
                    </span>
                  )}
                </figcaption>
                {pet.poses.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      // Starting a tour always restarts at the first pose, so a
                      // second viewing shows the same thing as the first.
                      setPoseIndex(0);
                      setPlayingId((id) => (id === pet.id ? null : pet.id));
                    }}
                    className="mono rounded-lg border px-3 py-1.5 text-xs transition hover:opacity-85"
                    style={playingId === pet.id
                      ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                      : { color: "var(--muted)", borderColor: "var(--line)" }}
                  >
                    {playingId === pet.id ? "■ Stop" : "▶ Animate"}
                  </button>
                )}
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

      {/* The listing text, for an admin checking what the AI or another admin
          wrote. A convenience, NOT a confidentiality boundary: description and
          tags ship in the public listing to every browser, because that is what
          makes client-side search work (§6.1). This decides who is SHOWN them,
          not who can obtain them. */}
      <ModalOverlay open={details !== null} onClose={() => setDetails(null)}
                    labelledBy="listing-text-title" maxWidth="max-w-md">
        {details && (
          <>
            <h2 id="listing-text-title" className="mb-1 text-sm font-semibold"
                style={{ color: "var(--heading)" }}>
              {details.display_name}
            </h2>
            <p className="mono mb-3 text-[11px]" style={{ color: "var(--faint)" }}>
              {details.id} · {details.animal} · {details.poses.length} pose
              {details.poses.length === 1 ? "" : "s"}
            </p>
            <p className="mono mb-1 text-[11px]" style={{ color: "var(--muted)" }}>
              Description
            </p>
            <p className="mb-3 text-sm leading-relaxed"
               style={{ color: details.description ? "var(--heading)" : "var(--faint)" }}>
              {details.description || NO_DESCRIPTION}
            </p>
            <p className="mono mb-1 text-[11px]" style={{ color: "var(--muted)" }}>
              Tags
            </p>
            {details.tags.length > 0 ? (
              <span className="mb-4 flex flex-wrap gap-1">
                {details.tags.map((tag) => (
                  <span key={tag} className="mono rounded border px-1.5 py-0.5 text-[10px]"
                        style={{ color: "var(--faint)", borderColor: "var(--line)" }}>
                    #{tag}
                  </span>
                ))}
              </span>
            ) : (
              <p className="mb-4 text-sm" style={{ color: "var(--faint)" }}>{NO_TAGS}</p>
            )}
            <button
              type="button"
              onClick={() => setDetails(null)}
              className="mono w-full rounded-lg border px-4 py-2.5 text-sm transition hover:opacity-85"
              style={{ background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }}
            >
              Close
            </button>
          </>
        )}
      </ModalOverlay>
    </main>
  );
}
