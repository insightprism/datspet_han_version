"use client";

/**
 * ArenaTrack — the racecourse as a RUNNER-GAME CAMERA (owner design,
 * 2026-08-02: "think like a game developer"). Each lane is a viewport onto a
 * fixed ~28 m window of track: the runner anchors part-way across the lane
 * and the WORLD — ground marks, hurdles, the finish line — scrolls past.
 * A pixel means a fixed slice of course on every course length, so a 64px
 * runner is ~2 real metres and a hurdle is hurdle-sized.
 *
 * Motion is CHASE-SMOOTHED: the drawn position approaches the integrator's
 * true distance exponentially (DISPLAY_CHASE_TAU_MS), so each answer is a
 * surge that plays out over real time, a lockout reads as deceleration, and
 * the animal never teleports. Render-only — the referee still scores the
 * impulse log (§7.4), and the hurdle GATE still clamps in the simulation;
 * the camera just draws the glide.
 *
 * This is the arena's second driver over the pet runtime (§1.2/§9.2): frame
 * primitives only, no ambient state machine, nothing in web/src/pet/ edited.
 * Hurdle jump poses trigger by screen-space collision (the owner's hidden
 * pixel): nose crosses the trigger line → jump; tail clears the obstacle →
 * run. Computed in world coordinates, camera-independent.
 */

import { useEffect, useRef } from "react";
import { applyTransform, getDisplayFrame, getPet, setAnim, setBgPos } from "@/pet";
import {
  APPARENT_SPEED_BASE_M_S, ARENA_PET_DISPLAY_SIZE_PX, CAMERA_ANCHOR_FRACTION,
  DISPLAY_CHASE_TAU_MS, DISPLAY_MAX_CHASE_M_S, DISPLAY_MIN_CREEP_M_S,
  HURDLE_HEIGHT_PX, HURDLE_JUMP_ARC_PX, HURDLE_TRIGGER_LEAD_PX,
  HURDLE_WIDTH_PX, LANE_HEIGHT_PX, SPRITE_RATE_MAX, SPRITE_RATE_MIN,
  TRACK_EDGE_PADDING_PX, TRACK_SCROLL_MARK_STEP_M, VIEWPORT_TRACK_METERS,
} from "./constants";
import type { LaneIntegrator, Impulse } from "./raceEngine";

export interface TrackLane {
  storeId: string;
  label: string;
  /** Shown on the lane — a hidden handicap is the failure §8.3.1 forbids. */
  handicapName: string;
  racingPose: string;
  /** Hurdle events (§6.6): the pose played over an obstacle — the first
   *  owned of jump/play, per the qualification's alternatives. */
  hopPose?: string;
  /** Rev.11: the tumble pose after a crash — first owned of sleep/sit/idle. */
  fallenPose?: string;
  /** Rev.11: the screen writes performance.now()+CRASH_FX_MS here on a crash;
   *  the driver shows the tumble + 💥 while now < value. Mutable ref so no
   *  re-render is needed mid-race. */
  crashFxRef?: { current: number };
  /** The lane's integrator, owned by the parent and rebuilt per run. */
  integrator: LaneIntegrator;
  /** The live (or recorded) impulse log. Parent appends; track only reads. */
  log: Impulse[];
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

/** The runner's nose sits here in WORLD px when its distance is 0. */
const NOSE_HOME_PX = TRACK_EDGE_PADDING_PX + ARENA_PET_DISPLAY_SIZE_PX;

function everyM(step: number, distanceM: number): number[] {
  const out: number[] = [];
  for (let d = step; d < distanceM; d += step) out.push(d);
  return out;
}

/** World-space left for a course position, as CSS — the driver publishes the
 *  live px-per-metre on the lane as a custom property, so world children
 *  position themselves without a re-render on resize. */
function worldLeftCss(d: number): string {
  return `calc(${NOSE_HOME_PX}px + ${d} * var(--px-per-m, 30px))`;
}

export default function ArenaTrack({
  lanes, distanceM, hurdlesEveryM, raceClock, onLaneFinish,
}: Props) {
  const laneElsRef = useRef<(HTMLDivElement | null)[]>([]);
  const worldElsRef = useRef<(HTMLDivElement | null)[]>([]);
  const spriteElsRef = useRef<(HTMLDivElement | null)[]>([]);
  const progressElsRef = useRef<(HTMLDivElement | null)[]>([]);
  const crashElsRef = useRef<(HTMLDivElement | null)[]>([]);
  /** Per-lane chase-smoothed distance — the DRAWN position. */
  const displayMRef = useRef<number[]>([]);
  const finishedRef = useRef<boolean[]>([]);
  const onLaneFinishRef = useRef(onLaneFinish);
  onLaneFinishRef.current = onLaneFinish;

  const laneKey = lanes.map((l) => l.storeId).join(",");

  useEffect(() => {
    finishedRef.current = lanes.map(() => false);
    displayMRef.current = lanes.map(() => 0);

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
      // The chase uses REAL elapsed time — under rAF throttling (occluded
      // window, battery saver) frames arrive seconds apart, and clamping
      // here would make the glide run arbitrarily slow. Only the sprite
      // frame-stepping below wants the clamp (a 2 s frame-burst would strobe).
      const rawDt = now - lastMs;
      const dt = Math.min(rawDt, 50);
      lastMs = now;
      const t = raceClock();
      // Exponential chase factor for this frame (§ constants: render-only).
      const chase = 1 - Math.exp(-rawDt / DISPLAY_CHASE_TAU_MS);

      lanes.forEach((lane, i) => {
        const pet = getPet(lane.storeId);
        const petEl = spriteElsRef.current[i];
        const laneEl = laneElsRef.current[i];
        const worldEl = worldElsRef.current[i];
        if (!pet || !petEl || !laneEl || !worldEl) return;

        if (t !== null) {
          lane.integrator.consume(lane.log, t);
          if (lane.integrator.finished && !finishedRef.current[i]) {
            finishedRef.current[i] = true;
            onLaneFinishRef.current?.(i, lane.integrator.finishMs ?? t);
          }
        }

        const laneW = laneEl.clientWidth;
        const pxPerM = laneW / VIEWPORT_TRACK_METERS;
        laneEl.style.setProperty("--px-per-m", `${pxPerM}px`);

        // The drawn position glides toward the truth; its derivative is the
        // APPARENT velocity that drives the legs.
        const prevDisplay = displayMRef.current[i];
        const gap = lane.integrator.distanceM - prevDisplay;
        // Exponential glide with a creep floor: while distance is owed the
        // runner keeps rolling at least DISPLAY_MIN_CREEP_M_S; it stops only
        // when truly caught up (a parked gate must read as parked).
        let step = gap * chase;
        if (gap > 0) {
          const minStep = DISPLAY_MIN_CREEP_M_S * (rawDt / 1000);
          const maxStep = DISPLAY_MAX_CHASE_M_S * (rawDt / 1000);
          step = Math.min(gap, Math.min(Math.max(step, minStep), maxStep));
        }
        const displayM = prevDisplay + step;
        displayMRef.current[i] = displayM;
        const apparentVel = rawDt > 0 ? (step / rawDt) * 1000 : 0;

        // Camera: keep the nose at the anchor, clamped to the course ends.
        const noseWorld = NOSE_HOME_PX + displayM * pxPerM;
        const anchorPx = laneW * CAMERA_ANCHOR_FRACTION;
        const finishWorld = NOSE_HOME_PX + distanceM * pxPerM;
        const camMax = Math.max(0, finishWorld + TRACK_EDGE_PADDING_PX - laneW);
        const cam = Math.min(Math.max(0, noseWorld - anchorPx), camMax);
        worldEl.style.transform = `translate3d(${-cam}px, 0, 0)`;
        pet.instance.x = noseWorld - ARENA_PET_DISPLAY_SIZE_PX - cam;

        const progressEl = progressElsRef.current[i];
        if (progressEl) {
          progressEl.textContent =
            `${Math.floor(lane.integrator.distanceM)} / ${distanceM} m`;
        }

        // Hurdle poses by collision (owner's hidden pixel), in world coords:
        // fire when the nose crosses the trigger line, release when the tail
        // clears the obstacle. A crash (Rev.11) overrides both: the fallen
        // pose + 💥 hold while the fx window is open. Never after finish.
        const crashing = (lane.crashFxRef?.current ?? 0) > now;
        const crashEl = crashElsRef.current[i];
        if (crashEl) {
          crashEl.style.display = crashing ? "block" : "none";
          if (crashing) crashEl.style.left = `${pet.instance.x + ARENA_PET_DISPLAY_SIZE_PX - 18}px`;
        }
        // The obstacle is SOLID (Rev.11): crossing it lifts the sprite on a
        // parabolic arc higher than the bar — the body visibly clears it.
        // Parked at the gate (integrator.atHurdle) the runner stays grounded.
        let liftY = 0;
        if (hurdlesEveryM && t !== null && !lane.integrator.finished) {
          let wanted = lane.racingPose;
          if (crashing) {
            wanted = lane.fallenPose ?? lane.racingPose;
          } else {
            const tailWorld = noseWorld - ARENA_PET_DISPLAY_SIZE_PX;
            for (let d = hurdlesEveryM; d < distanceM; d += hurdlesEveryM) {
              const obstacleWorld = NOSE_HOME_PX + d * pxPerM;
              const crossStart = obstacleWorld - HURDLE_TRIGGER_LEAD_PX;
              if (noseWorld >= crossStart
                  && tailWorld <= obstacleWorld + HURDLE_WIDTH_PX) {
                wanted = lane.hopPose ?? lane.racingPose;
                if (!lane.integrator.atHurdle) {
                  const crossLen = HURDLE_TRIGGER_LEAD_PX + HURDLE_WIDTH_PX
                    + ARENA_PET_DISPLAY_SIZE_PX;
                  const p = Math.min(Math.max(
                    (noseWorld - crossStart) / crossLen, 0), 1);
                  liftY = HURDLE_JUMP_ARC_PX * Math.sin(p * Math.PI);
                }
                break;
              }
            }
          }
          if (pet.anim !== wanted) setAnim(pet, wanted);
        }
        pet.instance.y = liftY;

        // Legs follow the APPARENT speed (§7.6): fast glide, fast strides;
        // stalled, a slow trot-in-place. Finished lanes idle at 1×.
        const anim = pet.anims[pet.anim];
        if (anim) {
          const rate = (t !== null && !lane.integrator.finished)
            ? Math.min(Math.max(
                apparentVel / APPARENT_SPEED_BASE_M_S,
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
          {/* The scrolling world: marks, hurdles, finish. Driver translates it. */}
          <div ref={(el) => { worldElsRef.current[i] = el; }}
            className="absolute inset-y-0 left-0 will-change-transform">
            {everyM(TRACK_SCROLL_MARK_STEP_M, distanceM).map((d) => (
              <div key={`m${d}`} className="pointer-events-none absolute bottom-0 top-0"
                style={{ left: worldLeftCss(d), width: 1, background: "rgba(255,255,255,0.07)" }}>
                <span className="absolute bottom-0.5 left-1 text-[9px]"
                  style={{ color: "var(--muted)", opacity: 0.8 }}>
                  {d}
                </span>
              </div>
            ))}
            {/* Real athletics hurdles (Rev.11): white top board on two legs. */}
            {hurdlesEveryM && everyM(hurdlesEveryM, distanceM).map((d) => (
              <div key={`h${d}`} className="pointer-events-none absolute"
                style={{
                  left: worldLeftCss(d), bottom: 2,
                  width: HURDLE_WIDTH_PX, height: HURDLE_HEIGHT_PX,
                }}>
                <div style={{
                  position: "absolute", top: 0, left: 0, right: 0, height: 7,
                  background: "#f2f2f2", borderRadius: 1,
                  boxShadow: "inset 0 -2px 0 #c9c9c9",
                }} />
                <div style={{
                  position: "absolute", top: 5, bottom: 0, left: 2, width: 2,
                  background: "#8a8a8a",
                }} />
                <div style={{
                  position: "absolute", top: 5, bottom: 0, right: 2, width: 2,
                  background: "#8a8a8a",
                }} />
              </div>
            ))}
            {/* The finish line. */}
            <div className="pointer-events-none absolute bottom-0 top-0"
              style={{
                left: worldLeftCss(distanceM),
                width: 3,
                backgroundImage:
                  "repeating-linear-gradient(180deg, #fff 0 6px, #333 6px 12px)",
                opacity: 0.6,
              }} />
            <div className="pointer-events-none absolute top-0.5 text-xs"
              style={{ left: `calc(${worldLeftCss(distanceM)} + 6px)` }}>
              🏁
            </div>
          </div>

          {/* Fixed overlays: who + how far. */}
          <div className="absolute left-2 top-1 text-xs" style={{ color: "var(--muted)" }}>
            {lane.label}
            {lane.handicapName !== "none" && (
              <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                style={{ background: "rgba(52,211,153,0.15)", color: "var(--green)" }}>
                🚀 {lane.handicapName.replace(/_/g, " ")}
              </span>
            )}
          </div>
          <div ref={(el) => { progressElsRef.current[i] = el; }}
            className="mono absolute right-2 top-1 text-[10px] tabular-nums"
            style={{ color: "var(--muted)" }}>
            0 / {distanceM} m
          </div>
          <div ref={(el) => { crashElsRef.current[i] = el; }}
            className="pointer-events-none absolute text-2xl"
            style={{ display: "none", bottom: LANE_HEIGHT_PX - 40 }}>
            💥
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
