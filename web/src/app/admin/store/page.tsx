"use client";

/**
 * Store admin (SPEC_PET_STORE §6.2) — the sixth admin surface: the shelf.
 *
 * Same gate posture as the other five (mount-time check; a 401 bounces through
 * the host admin-launch). Three panels in one page: the admin's own house
 * (the publish-from-pet picker — the designer is the authoring tool, §5.1),
 * the inventory table (every shelf state, newest first, with the live
 * sellability verdict),
 * and the listing editor. The AI's name idea is shown as a SUGGESTION next to
 * the name field, never auto-applied (§5.1).
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
  getDatsmeSession,
  listPets,
  storeAdmin,
  storePreviewUrl,
  type PetSummary,
  type StoreAdminListing,
  type StoreStatus,
} from "@/lib/api";
import ConfirmModal from "@/components/ConfirmModal";

/** The host's sparkle purple, so the affordance reads as the same feature
 *  across the two apps rather than as a DatsPet invention. */
const AI_SPARKLE_BG = "#7c3aed";
const AI_TAG_LABEL = "Write the description and tags with AI";
const DESCRIPTION_EMPTY_HINT =
  "No description yet — write one, or tap ✨ to generate.";
const TAGS_EMPTY_HINT = "#add #tags";

interface EditorState {
  id: string;
  display_name: string;
  description: string;
  tagsText: string;      // comma-separated in the field; normalized server-side
  animal: string;
  status: StoreStatus;
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
    status: listing.status,
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

  function applyResult(listing: StoreAdminListing, nameSuggestion?: string | null) {
    setInventory((prev) => {
      const rest = (prev ?? []).filter((p) => p.id !== listing.id);
      return [listing, ...rest];
    });
    setEditor(editorFromListing(listing));
    if (nameSuggestion !== undefined) setSuggestion(nameSuggestion);
  }

  async function publishFromPet(pet: PetSummary) {
    setBusy(true);
    setNotice("");
    try {
      const r = await storeAdmin.publishFromPet(pet.id);
      applyResult(r.listing, r.display_name_suggestion);
      setNotice(`"${pet.display_name}" is in intake — caption it, then choose a shelf state.`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not copy that pet.");
    } finally {
      setBusy(false);
    }
  }

  /** One save. The chosen status is applied with the edits, in that order, so
   *  a call that fixes `animal` AND shelves the row behaves like the two calls
   *  an admin would have made (§1.4). */
  async function saveEditor(status: StoreStatus) {
    if (!editor) return;
    setBusy(true);
    setNotice("");
    try {
      const r = await storeAdmin.update(editor.id, {
        display_name: editor.display_name,
        description: editor.description,
        tags: editor.tagsText.split(",").map((t) => t.trim()).filter(Boolean),
        animal: editor.animal,
        status,
        admin_note: editor.admin_note,
      });
      applyResult(r.listing);
      setNotice(status === "shelf"
        ? "On the shelf — shoppers can see it now."
        : `Saved as ${STORE_STATUS_LABEL[status].split(" — ")[0]}.`);
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
      applyResult(r.listing, r.display_name_suggestion);
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
      setNotice(`"${listing.display_name}" removed from the shelf.`);
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
          Design a pet the normal way, then copy it onto the shelf. Copying never
          moves your pet — the shelf gets its own.
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
                  Copy to shelf →
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* The shelf. */}
      <section className="mb-8">
        <h2 className="mb-2 text-sm font-semibold" style={{ color: "var(--heading)" }}>
          Shelf ({(inventory ?? []).length})
        </h2>
        {(inventory ?? []).length === 0 && (
          <p className="mono text-xs" style={{ color: "var(--faint)" }}>Nothing on the shelf yet.</p>
        )}
        <div className="flex flex-col gap-2">
          {(inventory ?? []).map((listing) => (
            <div key={listing.id}
                 className="flex items-center gap-3 rounded-xl border px-4 py-2"
                 style={{
                   background: "#151515",
                   borderColor: editor?.id === listing.id ? "var(--accent)" : "var(--line)",
                 }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={storePreviewUrl(listing.id)} alt="" width={40} height={40}
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
              {/* §10.4 — the ONE new thing donations add to the admin surface:
                  a read-time badge saying this arrived as a gift. With the
                  newest-first sort, that is the whole triage story; there is no
                  review queue and deliberately no workflow. */}
              {listing.donated_by && (
                <span className="mono text-[11px]" title={`Donated by ${listing.donated_by}`}
                      style={{ color: "var(--gold)" }}>
                  🎁 donated
                </span>
              )}
              <span className="mono text-[11px]"
                    style={{ color: listing.status === "shelf" ? "var(--green)"
                      : listing.status === "intake" ? "var(--gold)" : "var(--faint)" }}>
                {listing.status}
              </span>
              <button
                type="button"
                onClick={() => { setEditor(editorFromListing(listing)); setSuggestion(null); }}
                className="mono rounded-lg border px-3 py-1.5 text-xs transition hover:opacity-85"
                style={{ color: "var(--gold)", borderColor: "var(--line)" }}
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => setToDelete(listing)}
                className="mono rounded-lg border px-3 py-1.5 text-xs transition hover:opacity-85"
                style={{ color: "#f87171", borderColor: "rgba(239,68,68,0.35)" }}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* The editor. */}
      {editor && (
        <section className="rounded-xl border p-4" style={{ background: "#151515", borderColor: "var(--line)" }}>
          <h2 className="mb-3 text-sm font-semibold" style={{ color: "var(--heading)" }}>
            Listing: {editor.id}
          </h2>
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
                {/* Keyed on the PERSISTED row, not the editor's unsaved
                    dropdown: the server refuses ai-tag on a shelved listing, so
                    a button that appears the moment you pick "backroom" — before
                    saving — just 409s on click. */}
                {inventory?.find((l) => l.id === editor.id)?.status !== "shelf" && (
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
                        placeholder={editor.status === "shelf" ? "" : DESCRIPTION_EMPTY_HINT}
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
            <label className="text-xs" style={labelStyle}>
              Shelf state
              <select
                className={inputClass}
                value={editor.status}
                onChange={(e) => setEditor({ ...editor, status: e.target.value as StoreStatus })}
              >
                {STORE_STATUSES.map((s) => (
                  <option key={s} value={s}>{STORE_STATUS_LABEL[s]}</option>
                ))}
              </select>
            </label>
            {/* Asked for on the way to `archived` — the one transition whose
                reason nobody remembers in three months. Optional server-side;
                a required field would only ever collect the word "no". */}
            {editor.status === "archived" && (
              <label className="text-xs" style={labelStyle}>
                Why archived? (optional, for whoever reads this later)
                <input className={inputClass} value={editor.admin_note}
                       onChange={(e) => setEditor({ ...editor, admin_note: e.target.value })} />
              </label>
            )}
            <div className="mt-1 flex flex-wrap gap-2">
              {/* ONE save. The status selector above is what it applies —
                  two buttons could only ever express two of the four states. */}
              <button
                type="button" disabled={busy} onClick={() => saveEditor(editor.status)}
                className="mono rounded-lg border px-4 py-2 text-xs font-semibold transition hover:opacity-85 disabled:opacity-40"
                style={editor.status === "shelf"
                  ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                  : { color: "var(--heading)", borderColor: "var(--line)" }}
              >
                {editor.status === "shelf" ? "Save — on the shelf" : "Save"}
              </button>
              <button
                type="button" onClick={() => { setEditor(null); setSuggestion(null); }}
                className="mono rounded-lg border px-4 py-2 text-xs transition hover:opacity-85"
                style={{ color: "var(--muted)", borderColor: "var(--line)" }}
              >
                Close
              </button>
            </div>
          </div>
        </section>
      )}

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
        title={`Remove ${toDelete?.display_name ?? "this listing"} from the shelf?`}
        body="It disappears from the shop. Pets people already adopted are copies and are not affected."
        confirmLabel="Remove listing"
        onConfirm={confirmDelete}
        onCancel={() => setToDelete(null)}
      />
    </main>
  );
}
