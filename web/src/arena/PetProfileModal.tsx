"use client";

/**
 * The animated pet profile (owner ask, 2026-08-02): the store card's Animate
 * experience, reused for a pet you already OWN — the same PosePlayer the shop,
 * the result panel and the Motion Lab share (never a second frame-cycler that
 * could disagree about fps or columns), the same pose tour with live chips —
 * minus "Adopt this one", because it is already yours.
 *
 * Overlay shell is the shared <ModalOverlay> (scroll-lock, safe-areas, Escape,
 * height caps — the four things hand-rolled overlays always miss).
 */

import { useEffect, useState } from "react";
import ModalOverlay from "@/components/ModalOverlay";
import PosePlayer from "@/components/PosePlayer";
import { renamePet } from "@/lib/api";
import type { ArenaPetInfo } from "./gameTypes";
import StatBars from "./StatBars";

/** Same dwell the store tour uses — the two tours should feel identical. */
const POSE_DWELL_MS = 2600;

interface Props {
  /** The pet whose profile is open, or null = closed. */
  pet: ArenaPetInfo | null;
  onClose: () => void;
  /** Called after a successful rename so the owner list recomposes labels. */
  onRenamed?: (petId: string, petName: string | null) => void;
}

export default function PetProfileModal({ pet, onClose, onRenamed }: Props) {
  const [poseIndex, setPoseIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);

  // A fresh pet starts its tour from the first pose, playing, not editing.
  useEffect(() => {
    setPoseIndex(0);
    setPlaying(true);
    setEditingName(false);
    setRenameError(null);
  }, [pet?.id]);

  async function saveRename() {
    if (!pet) return;
    setEditingName(false);
    try {
      const res = await renamePet(pet.id, nameDraft);
      setRenameError(null);
      onRenamed?.(pet.id, res.pet_name);
    } catch (e) {
      setRenameError(e instanceof Error ? e.message : "Could not rename the pet");
    }
  }

  const poses = pet?.poses ?? [];
  useEffect(() => {
    if (!pet || !playing || poses.length <= 1) return;
    const timer = setInterval(
      () => setPoseIndex((i) => (i + 1) % poses.length), POSE_DWELL_MS);
    return () => clearInterval(timer);
  }, [pet, playing, poses.length]);

  return (
    <ModalOverlay open={pet !== null} onClose={onClose}
      labelledBy="pet-profile-title" maxWidth="max-w-sm">
      {pet && (
        <div className="flex flex-col gap-2 p-4">
          {poses.length > 0 ? (
            <PosePlayer petId={pet.id} pose={poses[poseIndex % poses.length]} fill />
          ) : (
            <div className="p-8 text-center" style={{ color: "var(--muted)" }}>
              This pet has no poses to play.
            </div>
          )}
          {editingName ? (
            <form className="flex items-center gap-1"
              onSubmit={(e) => { e.preventDefault(); void saveRename(); }}>
              <input autoFocus value={nameDraft} maxLength={24}
                onChange={(e) => setNameDraft(e.target.value)}
                placeholder="First name, e.g. Joe"
                className="input w-40"
                style={{ padding: "0.25rem 0.5rem", fontSize: 14 }} />
              <button type="submit" className="btn-ghost px-2 py-1 text-xs">✓</button>
            </form>
          ) : (
            <h3 id="pet-profile-title"
              className="flex items-center gap-1.5 text-lg font-semibold"
              style={{ color: "var(--heading)" }}>
              {pet.label}
              <button type="button" aria-label="Name this pet"
                className="text-sm opacity-50 transition hover:opacity-100"
                onClick={() => { setEditingName(true); setNameDraft(pet.pet_name ?? ""); }}>
                ✏️
              </button>
            </h3>
          )}
          {renameError && (
            <div className="text-xs" style={{ color: "#f87171" }}>{renameError}</div>
          )}
          {/* The chip list doubles as the tour's progress readout — you can
              see WHICH pose you are watching (the store card's pattern). */}
          {poses.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {poses.map((pose, i) => {
                const live = playing && i === poseIndex % poses.length;
                return (
                  <span key={pose}
                    className="mono rounded border px-1.5 py-0.5 text-[10px]"
                    style={live
                      ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                      : { color: "var(--muted)", borderColor: "var(--line)" }}>
                    {pose}
                  </span>
                );
              })}
            </span>
          )}
          <StatBars stats={pet.previewStats} />
          <div className="mt-1 flex gap-2">
            {poses.length > 1 && (
              <button type="button"
                className="mono flex-1 rounded-lg border px-3 py-1.5 text-xs transition hover:opacity-85"
                style={playing
                  ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                  : { color: "var(--muted)", borderColor: "var(--line)" }}
                onClick={() => {
                  setPoseIndex(0);
                  setPlaying((p) => !p);
                }}>
                {playing ? "■ Stop" : "▶ Animate"}
              </button>
            )}
            <button type="button" className="btn-ghost flex-1 text-xs" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      )}
    </ModalOverlay>
  );
}
