"use client";

/**
 * ArenaTrack — the racecourse, and the arena's DRIVER over the pet runtime
 * (SPEC_PET_ARENA §1.2/§9.2): it mounts the frame primitives (setBgPos,
 * applyTransform, setAnim via @/pet's sanctioned re-exports) and paces every
 * lane from the impulse stream. It does NOT mount useAnimationLoop or
 * useAutoStateMachine — a race is a third driver beside ambient life, not a
 * flag on it — and it edits nothing in web/src/pet/.
 *
 * Lanes are stacked containers; each sprite is absolutely positioned inside
 * its lane and moved by the same translate/rotate/scaleX composition the
 * ambient runtime uses (applyTransform). Sprite frame rate tracks the answer
 * tempo (§7.6) so a pet being driven hard visibly runs faster — the feedback
 * loop that makes answering feel like pedalling.
 *
 * The same component replays a recap (§8.8): hand it a scaled `raceClock` and
 * recorded logs and it is a playback, because the impulse log IS the race
 * (§7.4).
 */

import { useEffect, useRef } from "react";
import { applyTransform, getDisplayFrame, getPet, setAnim, setBgPos } from "@/pet";
import {
  ARENA_PET_DISPLAY_SIZE_PX, HURDLE_HOP_WINDOW_M, LANE_HEIGHT_PX,
  SPRITE_RATE_MAX, SPRITE_RATE_MIN, SPRITE_RATE_WINDOW_MS,
  TRACK_EDGE_PADDING_PX, TRACK_MARK_MAX_COUNT, TRACK_MARK_STEPS_M,
} from "./constants";
import type { LaneIntegrator, Impulse } from "./raceEngine";
import { recentAnswerRate } from "./raceEngine";

export interface TrackLane {
  storeId: string;
  label: string;
  /** Shown on the lane — a hidden handicap is the failure §8.3.1 forbids. */
  handicapName: string;
  racingPose: string;
  /** Hurdle events (§6.6): the pose played while crossing a hurdle mark —
   *  the first owned of jump/play, per the qualification's alternatives. */
  hopPose?: string;
  /** The lane's integrator, owned by the parent and rebuilt per run. */
  integrator: LaneIntegrator;
  /** The live (or recorded) impulse log. Parent appends; track only reads. */
  log: Impulse[];
}

/** The distance-marking step for a course: the smallest round step that keeps
 *  the track at no more than TRACK_MARK_MAX_COUNT marks (50 m → every 10 m,
 *  100 m → every 25 m, 300 m → every 100 m). */
function markStepM(distanceM: number): number {
  return TRACK_MARK_STEPS_M.find((step) => distanceM / step <= TRACK_MARK_MAX_COUNT)
    ?? TRACK_MARK_STEPS_M[TRACK_MARK_STEPS_M.length - 1];
}

function trackMarks(distanceM: number): number[] {
  return trackMarksEvery(distanceM, markStepM(distanceM));
}

function trackMarksEvery(distanceM: number, step: number): number[] {
  const marks: number[] = [];
  for (let d = step; d < distanceM; d += step) marks.push(d);
  return marks;
}

/** A mark's CSS left, aligned to where the runner's NOSE is at that distance —
 *  the same mapping the driver uses for the sprite (nose = sprite right edge,
 *  which crosses the finish line exactly at full distance). */
function markLeftCss(d: number, distanceM: number): string {
  const noseOffsetPx = TRACK_EDGE_PADDING_PX + ARENA_PET_DISPLAY_SIZE_PX;
  const usablePx = ARENA_PET_DISPLAY_SIZE_PX + 2 * TRACK_EDGE_PADDING_PX;
  return `calc(${noseOffsetPx}px + ${d / distanceM} * (100% - ${usablePx}px))`;
}

interface Props {
  lanes: TrackLane[];
  distanceM: number;
  /** Hurdle marks every N metres (§6.6) — presentation only. */
  hurdlesEveryM?: number;
  /** Current race time in ms, or null before the gun. Live races return
   *  now − gun; recaps return a scaled clock. */
  raceClock: () => number | null;
  onLaneFinish?: (laneIndex: number, finishMs: number) => void;
}

export default function ArenaTrack({
  lanes, distanceM, hurdlesEveryM, raceClock, onLaneFinish,
}: Props) {
  const laneElsRef = useRef<(HTMLDivElement | null)[]>([]);
  const spriteElsRef = useRef<(HTMLDivElement | null)[]>([]);
  // The live "how far he got" readout — written by the driver loop directly
  // (textContent, no React re-render at 60 fps), like every other per-frame
  // update on this track.
  const progressElsRef = useRef<(HTMLDivElement | null)[]>([]);
  // Per-lane finish flag so onLaneFinish fires exactly once.
  const finishedRef = useRef<boolean[]>([]);
  const onLaneFinishRef = useRef(onLaneFinish);
  onLaneFinishRef.current = onLaneFinish;

  const laneKey = lanes.map((l) => l.storeId).join(",");

  useEffect(() => {
    finishedRef.current = lanes.map(() => false);

    // Bind each lane's DOM onto its pet instance — the same registration
    // PetCanvas performs, done here because arena sprites are positioned
    // inside a lane, not fixed to the viewport.
    lanes.forEach((lane, i) => {
      const pet = getPet(lane.storeId);
      const petEl = spriteElsRef.current[i];
      const laneEl = laneElsRef.current[i];
      if (!pet || !petEl || !laneEl) return;
      pet.instance.petEl = petEl;
      pet.instance.stageEl = laneEl;
      pet.instance.x = TRACK_EDGE_PADDING_PX;
      pet.instance.y = 0;
      pet.instance.targetX = null;
      pet.instance.targetY = null;
      pet.facing = 1;

      const df = getDisplayFrame();
      petEl.style.backgroundImage = `url('${pet.sheetUrl}')`;
      petEl.style.backgroundSize = `${pet.sheetCols * df}px ${pet.sheetRows * df}px`;
      setAnim(pet, lane.racingPose, { force: true });
      setBgPos(pet, petEl, pet.anims[pet.anim]?.frames?.[0] ?? 0);
      applyTransform(pet);
    });

    let rafId: number | null = null;
    let lastMs = performance.now();

    function tick(now: number) {
      const dt = Math.min(now - lastMs, 50);
      lastMs = now;
      const t = raceClock();

      lanes.forEach((lane, i) => {
        const pet = getPet(lane.storeId);
        const petEl = spriteElsRef.current[i];
        const laneEl = laneElsRef.current[i];
        if (!pet || !petEl || !laneEl) return;

        if (t !== null) {
          lane.integrator.consume(lane.log, t);
          if (lane.integrator.finished && !finishedRef.current[i]) {
            finishedRef.current[i] = true;
            setAnim(pet, "idle");
            onLaneFinishRef.current?.(i, lane.integrator.finishMs ?? t);
          }
        }

        // Position: distance fraction across the usable lane width.
        const usable = Math.max(
          laneEl.clientWidth - ARENA_PET_DISPLAY_SIZE_PX - 2 * TRACK_EDGE_PADDING_PX, 1);
        pet.instance.x =
          TRACK_EDGE_PADDING_PX + lane.integrator.distanceFraction * usable;

        const progressEl = progressElsRef.current[i];
        if (progressEl) {
          progressEl.textContent =
            `${Math.floor(lane.integrator.distanceM)} / ${distanceM} m`;
        }

        // Hurdles (§6.6, presentation): the runner plays its hop pose while
        // crossing a mark, its racing pose between them. Never after finish.
        if (hurdlesEveryM && t !== null && !lane.integrator.finished) {
          const sinceHurdle = lane.integrator.distanceM % hurdlesEveryM;
          const nearHurdle = lane.integrator.distanceM > 1 && (
            sinceHurdle < HURDLE_HOP_WINDOW_M
            || hurdlesEveryM - sinceHurdle < HURDLE_HOP_WINDOW_M);
          const wanted = nearHurdle && lane.hopPose ? lane.hopPose : lane.racingPose;
          if (pet.anim !== wanted) setAnim(pet, wanted);
        }

        // Frame advance at answer tempo (§7.6). Finished lanes idle at 1×.
        const anim = pet.anims[pet.anim];
        if (anim) {
          const rate = (t !== null && !lane.integrator.finished)
            ? Math.min(Math.max(
                recentAnswerRate(lane.log, t, SPRITE_RATE_WINDOW_MS),
                SPRITE_RATE_MIN), SPRITE_RATE_MAX)
            : 1;
          pet.frameElapsedMs += dt * rate;
          const msPerFrame = 1000 / anim.fps;
          while (pet.frameElapsedMs >= msPerFrame) {
            pet.frameElapsedMs -= msPerFrame;
            pet.frameIdx = (pet.frameIdx + 1 >= anim.frames.length)
              ? (anim.loop ? 0 : anim.frames.length - 1)
              : pet.frameIdx + 1;
          }
          setBgPos(pet, petEl, anim.frames[pet.frameIdx]);
        }

        applyTransform(pet, dt);
      });

      rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      lanes.forEach((lane) => {
        const pet = getPet(lane.storeId);
        if (pet) {
          pet.instance.petEl = null;
          pet.instance.stageEl = null;
        }
      });
    };
    // Rebuild the driver when the lane set (or the run) changes; `lanes`
    // carries fresh integrators per run via the parent's key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laneKey, raceClock]);

  return (
    <div className="flex flex-col gap-1">
      {lanes.map((lane, i) => (
        <div
          key={`${lane.storeId}-${i}`}
          ref={(el) => { laneElsRef.current[i] = el; }}
          className="relative overflow-hidden rounded-lg"
          style={{
            height: LANE_HEIGHT_PX,
            background: "linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.06))",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <div className="absolute left-2 top-1 text-xs" style={{ color: "var(--muted)" }}>
            {lane.label}
            {lane.handicapName !== "none" && (
              <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                style={{ background: "rgba(52,211,153,0.15)", color: "var(--green)" }}>
                🚀 {lane.handicapName.replace(/_/g, " ")}
              </span>
            )}
          </div>
          {/* Distance markings, like a real track — the runner is literally
              "on the 40" (owner). Aligned to the nose, same mapping as the
              finish line. */}
          {trackMarks(distanceM).map((d) => (
            <div key={d} className="pointer-events-none absolute bottom-0 top-0"
              style={{
                left: markLeftCss(d, distanceM),
                width: 1,
                background: "rgba(255,255,255,0.08)",
              }}>
              <span className="absolute bottom-0.5 left-1 text-[9px]"
                style={{ color: "var(--muted)", opacity: 0.8 }}>
                {d}
              </span>
            </div>
          ))}
          {/* Hurdle marks (§6.6) — same nose-aligned mapping as the numbers. */}
          {hurdlesEveryM && trackMarksEvery(distanceM, hurdlesEveryM).map((d) => (
            <div key={`h${d}`} className="pointer-events-none absolute bottom-1 text-sm"
              style={{ left: markLeftCss(d, distanceM), opacity: 0.5 }}>
              🚧
            </div>
          ))}
          {/* The finish line. */}
          <div className="absolute bottom-0 top-0"
            style={{
              right: TRACK_EDGE_PADDING_PX,
              width: 3,
              backgroundImage:
                "repeating-linear-gradient(180deg, #fff 0 6px, #333 6px 12px)",
              opacity: 0.5,
            }} />
          <div ref={(el) => { progressElsRef.current[i] = el; }}
            className="mono absolute right-2 top-1 text-[10px] tabular-nums"
            style={{ color: "var(--muted)" }}>
            0 / {distanceM} m
          </div>
          <div
            ref={(el) => { spriteElsRef.current[i] = el; }}
            className="absolute"
            style={{
              bottom: 4,
              left: 0,
              width: "var(--pet-display-size, 96px)",
              height: "var(--pet-display-size, 96px)",
              backgroundRepeat: "no-repeat",
              backgroundPosition: "0 0",
            }}
          />
        </div>
      ))}
    </div>
  );
}
