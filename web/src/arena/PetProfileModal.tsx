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
import type { ArenaPetInfo } from "./gameTypes";
import StatBars from "./StatBars";

/** Same dwell the store tour uses — the two tours should feel identical. */
const POSE_DWELL_MS = 2600;

interface Props {
  /** The pet whose profile is open, or null = closed. */
  pet: ArenaPetInfo | null;
  onClose: () => void;
}

export default function PetProfileModal({ pet, onClose }: Props) {
  const [poseIndex, setPoseIndex] = useState(0);
  const [playing, setPlaying] = useState(true);

  // A fresh pet starts its tour from the first pose, playing.
  useEffect(() => {
    setPoseIndex(0);
    setPlaying(true);
  }, [pet?.id]);

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
          <h3 id="pet-profile-title" className="text-lg font-semibold"
            style={{ color: "var(--heading)" }}>
            {pet.label}
          </h3>
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
