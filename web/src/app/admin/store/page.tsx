"use client";

/**
 * Store admin (SPEC_PET_STORE §6.2) — the sixth admin surface: the shelf.
 *
 * Same gate posture as the other five (mount-time check; a 401 bounces through
 * the host admin-launch). Three panels: the admin's own house (the
 * publish-from-pet picker — the designer is the authoring tool, §5.1), the
 * inventory, and a listing dialog.
 *
 * THE SPLIT THIS PAGE IS BUILT ON (§6.2c): a row owns the LIFECYCLE, the
 * dialog owns the TEXT. Shelf state moves on every triage pass and must cost
 * two clicks in the row itself; name/description/tags are written once and
 * rarely revisited, so they live behind an ⓘ. They changed together until
 * 2026-07-31, which meant moving one pet one state opened a full editor below
 * the fold — unusable at ten listings and impossible at a hundred a day.
 *
 * Listing text is never written by AI as a side effect of anything (§4). A new
 * row arrives with an empty description and no tags; the ✨ next to the
 * description writes both, and only from its confirm dialog. This mirrors the
 * host's AI-tag door: one call for caption AND tags, an overwrite rather than a
 * merge, and therefore a confirm in front of it.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AdminApiError,
  STORE_STATUSES,
  STORE_STATUS_LABEL,
  STORE_STATUS_SHORT,
  getDatsmeSession,
  listPets,
  storeAdmin,
  type PetSummary,
  type StoreAdminListing,
  type StoreStatus,
} from "@/lib/api";
import ConfirmModal from "@/components/ConfirmModal";
import ModalOverlay from "@/components/ModalOverlay";

/** The host's sparkle purple, so the affordance reads as the same feature
 *  across the two apps rather than as a DatsPet invention. */
const AI_SPARKLE_BG = "#7c3aed";
const AI_TAG_LABEL = "Write the description and tags with AI";
const DESCRIPTION_EMPTY_HINT =
  "No description yet — write one, or tap ✨ to generate.";
const TAGS_EMPTY_HINT = "#add #tags";
const DETAILS_LABEL = "Listing details — name, description, tags";

/** Per-state colour for the row's state control. `shelf` is the only one that
 *  means "shoppers can see this", so it is the only green. */
const STATUS_COLOR: Record<StoreStatus, string> = {
  intake: "var(--gold)",
  shelf: "var(--green)",
  backroom: "var(--muted)",
  archived: "var(--faint)",
};

interface EditorState {
  id: string;
  display_name: string;
  description: string;
  tagsText: string;      // comma-separated in the field; normalized server-side
  animal: string;
  admin_note: string;
  /** Read-only. Once set, `animal` is frozen for good (§1.3) — moving the row
   *  back off the shelf does NOT re-open it. */
  first_shelved_at: number | null;
}

function editorFromListing(listing: StoreAdminListing): EditorState {
  return {
    id: listing.id,
    display_name: listing.display_name,
    description: listing.description,
    tagsText: listing.tags.join(", "),
    animal: listing.animal,
    admin_note: listing.admin_note ?? "",
    first_shelved_at: listing.first_shelved_at ?? null,
  };
}

export default function StoreAdminPage() {
  const [inventory, setInventory] = useState<StoreAdminListing[] | null>(null);
  const [housePets, setHousePets] = useState<PetSummary[]>([]);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<StoreAdminListing | null>(null);
  const [gateState, setGateState] = useState<"checking" | "ok" | "denied">("checking");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  // What each row's state control is SET to, when that differs from what is
  // stored. Keyed by id rather than held per row so the whole page has one
  // answer to "what is unsaved", which is what lets Save appear only where
  // there is something to save.
  const [pendingStatus, setPendingStatus] = useState<Record<string, StoreStatus>>({});
  const [statusBusyId, setStatusBusyId] = useState<string | null>(null);
  // The AI-tag flow owns its own three-state slice rather than riding `busy`:
  // the dialog has to stay open on failure to show the error, which a shared
  // page-wide flag cannot express.
  const [aiTagOpen, setAiTagOpen] = useState(false);
  const [aiTagPending, setAiTagPending] = useState(false);
  const [aiTagError, setAiTagError] = useState("");

  const refresh = useCallback(async () => {
    const r = await storeAdmin.list();
    setInventory(r.pets);
    setGateState("ok");
    // The picker reads the admin's OWN house — publish-from-pet is scoped to it
    // server-side (§3.2); this list is simply the same truth, shown.
    listPets().then(setHousePets).catch(() => setHousePets([]));
  }, []);

  useEffect(() => {
    refresh().catch(async (e) => {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) {
          window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/store`;
          return;
        }
        setGateState("denied");
      } else {
        setNotice("Could not load the store inventory.");
        setGateState("denied");
      }
    });
  }, [refresh]);

  /** Replace a row IN PLACE. Never reorders: a listing that jumps to the top
   *  the moment you change its state moves the next row under your cursor,
   *  which is how a triage pass mis-files a pet. */
  function mergeListing(listing: StoreAdminListing) {
    setInventory((prev) =>
      (prev ?? []).map((p) => (p.id === listing.id ? listing : p)));
  }

  function applyToEditor(listing: StoreAdminListing, nameSuggestion?: string | null) {
    mergeListing(listing);
    setEditor(editorFromListing(listing));
    if (nameSuggestion !== undefined) setSuggestion(nameSuggestion);
  }

  const statusOf = (l: StoreAdminListing): StoreStatus => pendingStatus[l.id] ?? l.status;

  function chooseStatus(listing: StoreAdminListing, next: StoreStatus) {
    setPendingStatus((prev) => {
      const rest = { ...prev };
      // Choosing the stored value back is not a change — drop the entry so the
      // Save button disappears rather than saving a no-op.
      if (next === listing.status) delete rest[listing.id];
      else rest[listing.id] = next;
      return rest;
    });
  }

  /** The triage action: one call, one field, no read-modify-write (§3.2). */
  async function saveStatus(listing: StoreAdminListing) {
    const next = statusOf(listing);
    if (next === listing.status) return;
    setStatusBusyId(listing.id);
    setNotice("");
    try {
      const r = await storeAdmin.setStatus(listing.id, next);
      mergeListing(r.listing);
      chooseStatus(r.listing, r.listing.status);
      setNotice(next === "shelf"
        ? `"${r.listing.display_name}" is on the shelf — shoppers can see it now.`
        : `"${r.listing.display_name}" moved to ${STORE_STATUS_SHORT[next].toLowerCase()}.`);
    } catch (e) {
      if (e instanceof AdminApiError && e.errors.length > 0) {
        setNotice(`Not sellable yet: ${e.errors.join("; ")}`);
      } else {
        setNotice(e instanceof Error ? e.message : "Could not change the state.");
      }
    } finally {
      setStatusBusyId(null);
    }
  }

  async function publishFromPet(pet: PetSummary) {
    setBusy(true);
    setNotice("");
    try {
      const r = await storeAdmin.publishFromPet(pet.id);
      // Genuinely new, so it DOES go to the front — the one case where the
      // list reorders, and the row the admin is about to caption.
      setInventory((prev) => [r.listing, ...(prev ?? [])]);
      setEditor(editorFromListing(r.listing));
      setSuggestion(r.display_name_suggestion);
      setNotice(`"${pet.display_name}" is in intake — caption it, then set its state.`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not copy that pet.");
    } finally {
      setBusy(false);
    }
  }

  /** Save the AUTHORED fields. Shelf state is the row's job, not this dialog's. */
  async function saveEditor() {
    if (!editor) return;
    setBusy(true);
    setNotice("");
    try {
      const r = await storeAdmin.update(editor.id, {
        display_name: editor.display_name,
        description: editor.description,
        tags: editor.tagsText.split(",").map((t) => t.trim()).filter(Boolean),
        animal: editor.animal,
        admin_note: editor.admin_note,
      });
      mergeListing(r.listing);
      setEditor(null);
      setNotice(`Saved "${r.listing.display_name}".`);
    } catch (e) {
      if (e instanceof AdminApiError && e.errors.length > 0) {
        setNotice(`Not sellable yet: ${e.errors.join("; ")}`);
      } else {
        setNotice(e instanceof Error ? e.message : "Save failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  /** The AI writes description + tags — only ever from the confirm dialog
   *  (SPEC_PET_STORE §4). It OVERWRITES both, which is exactly why the sparkle
   *  opens a dialog instead of firing: the host's AI-tag door makes the same
   *  trade, and the confirm is where the overwrite is disclosed. */
  async function runAiTag() {
    if (!editor) return;
    setAiTagPending(true);
    setAiTagError("");
    try {
      const r = await storeAdmin.aiTag(editor.id);
      applyToEditor(r.listing, r.display_name_suggestion);
      setAiTagOpen(false);
      setNotice("The AI wrote the description and tags — edit them freely.");
    } catch (e) {
      // Inline in the dialog, never a toast, and the dialog STAYS OPEN so the
      // admin can retry or cancel without re-finding the button.
      setAiTagError(e instanceof Error ? e.message : "AI tagging failed.");
    } finally {
      setAiTagPending(false);
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    const listing = toDelete;
    setToDelete(null);
    try {
      await storeAdmin.remove(listing.id);
      setInventory((prev) => (prev ?? []).filter((p) => p.id !== listing.id));
      if (editor?.id === listing.id) setEditor(null);
      setNotice(`"${listing.display_name}" removed from the store.`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Delete failed.");
    }
  }

  if (gateState === "checking") {
    return <main className="mx-auto max-w-5xl px-6 py-10 mono text-sm" style={{ color: "var(--faint)" }}>Checking access…</main>;
  }
  if (gateState === "denied") {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="mono text-sm" style={{ color: "var(--faint)" }}>
          {notice || "Admin access required."}
        </p>
      </main>
    );
  }

  const labelStyle = { color: "var(--muted)" } as const;
  const inputClass = "input w-full";
  const iconButtonClass =
    "mono flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border text-xs transition hover:opacity-85";
  const editorListing = editor
    ? (inventory ?? []).find((l) => l.id === editor.id) ?? null
    : null;

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold" style={{ color: "var(--heading)" }}>Pet Store</h1>
        <nav className="mono flex gap-4 text-xs">
          <Link href="/admin/motions" className="hover:opacity-80" style={{ color: "var(--gold)" }}>motions</Link>
          <Link href="/admin/design" className="hover:opacity-80" style={{ color: "var(--gold)" }}>design</Link>
          <Link href="/admin/ai" className="hover:opacity-80" style={{ color: "var(--gold)" }}>ai</Link>
          <Link href="/admin/settings" className="hover:opacity-80" style={{ color: "var(--gold)" }}>settings</Link>
        </nav>
      </div>

      {notice && (
        <div className="mono mb-4 text-xs" style={{ color: "var(--gold)" }}>{notice}</div>
      )}

      {/* The stocking door: the admin's own house (§5.1). */}
      <section className="mb-8">
        <h2 className="mb-2 text-sm font-semibold" style={{ color: "var(--heading)" }}>
          Stock from your house
        </h2>
        <p className="mono mb-3 text-xs" style={labelStyle}>
          Design a pet the normal way, then copy it into the store. Copying never
          moves your pet — the store gets its own, and it lands in intake.
        </p>
        {housePets.length === 0 ? (
          <p className="mono text-xs" style={{ color: "var(--faint)" }}>
            Your house is empty — design a pet first.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {housePets.map((pet) => (
              <div key={pet.id} className="flex items-center justify-between gap-3 rounded-xl border px-4 py-2"
                   style={{ background: "#151515", borderColor: "var(--line)" }}>
                <div className="min-w-0">
                  <span className="text-sm" style={{ color: "var(--heading)" }}>{pet.display_name}</span>
                  <span className="mono ml-2 text-[11px]" style={{ color: "var(--faint)" }}>{pet.breed_id}</span>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => publishFromPet(pet)}
                  className="mono shrink-0 rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85 disabled:opacity-40"
                  style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
                >
                  Copy to store →
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* The inventory — every shelf state, not just the shelf. Calling this
          "Shelf" was a straight lie about `intake` rows: it told the admin the
          donation she was looking at was already for sale (§1.4). */}
      <section className="mb-8">
        <h2 className="mb-2 text-sm font-semibold" style={{ color: "var(--heading)" }}>
          Inventory ({(inventory ?? []).length})
        </h2>
        <p className="mono mb-3 text-xs" style={labelStyle}>
          Every state, newest first — donations land at the top in{" "}
          <span style={{ color: "var(--gold)" }}>intake</span>. Change a state
          right here; ⓘ opens the listing text.
        </p>
        {(inventory ?? []).length === 0 && (
          <p className="mono text-xs" style={{ color: "var(--faint)" }}>Nothing in the store yet.</p>
        )}
        <div className="flex flex-col gap-2">
          {(inventory ?? []).map((listing) => {
            const chosen = statusOf(listing);
            const dirty = chosen !== listing.status;
            const rowBusy = statusBusyId === listing.id;
            return (
            <div key={listing.id}
                 className="flex items-center gap-3 rounded-xl border px-4 py-2"
                 style={{
                   background: "#151515",
                   borderColor: dirty ? "var(--gold)" : "var(--line)",
                 }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={storeAdmin.previewUrl(listing.id)} alt="" width={40} height={40}
                   style={{ borderRadius: 8, objectFit: "contain" }} />
              <div className="min-w-0 flex-1">
                <span className="text-sm" style={{ color: "var(--heading)" }}>{listing.display_name}</span>
                <span className="mono ml-2 text-[11px]" style={{ color: "var(--faint)" }}>
                  {listing.animal} · {listing.pose_count} poses
                </span>
                {(listing.sellability_errors ?? []).length > 0 && (
                  <span className="mono ml-2 text-[11px]" style={{ color: "#f87171" }}>
                    ⚠ not sellable
                  </span>
                )}
              </div>
              {/* The lifecycle control, in the row. Picking a state does not
                  commit it — a select that saves on change fires on a stray
                  scroll wheel, and this list is the one place a mis-set state
                  puts a pet in front of shoppers. */}
              <select
                value={chosen}
                disabled={rowBusy}
                aria-label={`Shelf state for ${listing.display_name}`}
                onChange={(e) => chooseStatus(listing, e.target.value as StoreStatus)}
                className="mono shrink-0 rounded-lg border px-2 py-1.5 text-xs disabled:opacity-40"
                style={{
                  background: "#101010",
                  color: STATUS_COLOR[chosen],
                  borderColor: dirty ? "var(--gold)" : "var(--line)",
                }}
              >
                {STORE_STATUSES.map((s) => (
                  <option key={s} value={s} style={{ color: "var(--heading)" }}>
                    {STORE_STATUS_SHORT[s]}
                  </option>
                ))}
              </select>
              {/* Only where there is something to save. A permanent Save on
                  every row is a hundred buttons that do nothing. */}
              {dirty && (
                <button
                  type="button"
                  disabled={rowBusy}
                  onClick={() => saveStatus(listing)}
                  className="mono shrink-0 rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85 disabled:opacity-40"
                  style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
                >
                  {rowBusy ? "Saving…" : "Save"}
                </button>
              )}
              <button
                type="button"
                title={DETAILS_LABEL}
                aria-label={`${DETAILS_LABEL} for ${listing.display_name}`}
                onClick={() => { setEditor(editorFromListing(listing)); setSuggestion(null); }}
                className={iconButtonClass}
                style={{ color: "var(--gold)", borderColor: "var(--line)" }}
              >
                ⓘ
              </button>
              <button
                type="button"
                title={`Remove ${listing.display_name} from the store`}
                aria-label={`Remove ${listing.display_name} from the store`}
                onClick={() => setToDelete(listing)}
                className={iconButtonClass}
                style={{ color: "#f87171", borderColor: "rgba(239,68,68,0.35)" }}
              >
                ✕
              </button>
            </div>
            );
          })}
        </div>
      </section>

      {/* The listing text, in a dialog. It carries NO shelf-state control: the
          row owns that, and two places to change one thing is how they
          disagree. */}
      <ModalOverlay open={editor !== null} onClose={() => setEditor(null)}
                    labelledBy="listing-title" maxWidth="max-w-lg">
        {editor && (
          <>
            <h2 id="listing-title" className="mb-1 text-sm font-semibold"
                style={{ color: "var(--heading)" }}>
              Listing details
            </h2>
            <p className="mono mb-3 text-[11px]" style={{ color: "var(--faint)" }}>
              {editor.id}
              {editorListing?.donated_by && (
                <span style={{ color: "var(--gold)" }}>
                  {" · "}donated by {editorListing.donated_by}
                </span>
              )}
              {/* The full sentence, which the row's one-word select cannot
                  carry — this is where there is room to say what a state
                  MEANS, and the only place it is spelled out. */}
              {editorListing && (
                <span style={{ color: STATUS_COLOR[editorListing.status] }}>
                  {" · "}{STORE_STATUS_LABEL[editorListing.status]}
                </span>
              )}
            </p>
            <div className="flex flex-col gap-3">
              <label className="text-xs" style={labelStyle}>
                Name
                <input className={inputClass} value={editor.display_name}
                       onChange={(e) => setEditor({ ...editor, display_name: e.target.value })} />
                {suggestion && suggestion !== editor.display_name && (
                  <button
                    type="button"
                    onClick={() => setEditor({ ...editor, display_name: suggestion })}
                    className="mono mt-1 text-[11px] hover:opacity-80"
                    style={{ color: "var(--gold)" }}
                  >
                    AI suggests: “{suggestion}” — use it
                  </button>
                )}
              </label>
              <div className="text-xs" style={labelStyle}>
                <div className="flex items-center gap-2">
                  <span>Description</span>
                  {/* Keyed on the PERSISTED row: the server refuses ai-tag on a
                      shelved listing, so offering it there would just 409. */}
                  {editorListing?.status !== "shelf" && (
                    <button
                      type="button"
                      onClick={() => { setAiTagError(""); setAiTagOpen(true); }}
                      title={AI_TAG_LABEL}
                      aria-label={AI_TAG_LABEL}
                      className="flex h-6 w-6 items-center justify-center rounded-full text-xs transition hover:opacity-85"
                      style={{ backgroundColor: AI_SPARKLE_BG, color: "#fff" }}
                    >
                      ✨
                    </button>
                  )}
                </div>
                <textarea className={inputClass} rows={3} value={editor.description}
                          placeholder={DESCRIPTION_EMPTY_HINT}
                          onChange={(e) => setEditor({ ...editor, description: e.target.value })} />
              </div>
              <label className="text-xs" style={labelStyle}>
                Tags (comma-separated; lowercased and deduped on save)
                <input className={inputClass} value={editor.tagsText}
                       placeholder={TAGS_EMPTY_HINT}
                       onChange={(e) => setEditor({ ...editor, tagsText: e.target.value })} />
              </label>
              <label className="text-xs" style={labelStyle}>
                Animal {editor.first_shelved_at !== null && (
                  <span className="mono" style={{ color: "var(--faint)" }}>
                    (fixed — this listing has been on the shelf; §1.3)
                  </span>
                )}
                <input className={inputClass} value={editor.animal}
                       disabled={editor.first_shelved_at !== null}
                       onChange={(e) => setEditor({ ...editor, animal: e.target.value })} />
              </label>
              {/* Always present rather than appearing on the way to `archived`:
                  the state control moved to the row, so there is no longer a
                  moment in this dialog to ask. Optional, as it always was — a
                  required field would only ever collect the word "no". */}
              <label className="text-xs" style={labelStyle}>
                Note (why it was archived, or anything worth remembering)
                <input className={inputClass} value={editor.admin_note}
                       onChange={(e) => setEditor({ ...editor, admin_note: e.target.value })} />
              </label>
              <div className="mt-1 flex flex-wrap gap-3">
                <button
                  type="button" disabled={busy} onClick={saveEditor}
                  className="mono flex-1 rounded-lg border px-4 py-2.5 text-sm font-semibold transition hover:opacity-85 disabled:opacity-40"
                  style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)", borderColor: "rgba(99,102,241,0.5)" }}
                >
                  {busy ? "Saving…" : "Save"}
                </button>
                <button
                  type="button" onClick={() => { setEditor(null); setSuggestion(null); }}
                  className="mono flex-1 rounded-lg border px-4 py-2.5 text-sm transition hover:opacity-85"
                  style={{ background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }}
                >
                  Close
                </button>
              </div>
            </div>
          </>
        )}
      </ModalOverlay>

      <ConfirmModal
        open={aiTagOpen}
        title="Write the description and tags with AI?"
        body="This replaces the current description and tags. You can edit the result before publishing."
        confirmLabel="Generate"
        pendingLabel="Analyzing…"
        pending={aiTagPending}
        error={aiTagError}
        tone="primary"
        onConfirm={runAiTag}
        onCancel={() => setAiTagOpen(false)}
      />

      <ConfirmModal
        open={toDelete !== null}
        title={`Remove ${toDelete?.display_name ?? "this listing"} from the store?`}
        body="It disappears from the shop. Pets people already adopted are copies and are not affected."
        confirmLabel="Remove listing"
        onConfirm={confirmDelete}
        onCancel={() => setToDelete(null)}
      />
    </main>
  );
}
