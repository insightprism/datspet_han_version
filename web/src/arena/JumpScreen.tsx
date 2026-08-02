"use client";

/**
 * JumpScreen — the Tier-2 field event (SPEC_PET_ARENA §6.6): three run-ups on
 * a fixed clock, an automatic leap at each buzzer, best of three. The same
 * challenge panel drives it — a jump is a burst-rate contest the way a race
 * is a sustained-rate contest, so the player's job never changes shape.
 *
 * The lane driver here is DELIBERATELY separate from ArenaTrack's: a race
 * integrates distance continuously; a jump approaches, leaps, lands and walks
 * back — different cadence, different code, same engine primitives. Attempt
 * timing comes from fieldJump's declared schedule, never from UI state, so
 * the recorded log replays to the same distances (§7.4).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { applyTransform, getDisplayFrame, getPet, setAnim, setBgPos } from "@/pet";
import { botImpulseLog } from "./bot";
import type { ArenaChallenge } from "./challenges/registry";
import {
  ARENA_PET_DISPLAY_SIZE_PX, COUNTDOWN_SECONDS, JUMP_PIT_DISPLAY_MAX_M,
  LANE_HEIGHT_PX, SPRITE_RATE_MAX, SPRITE_RATE_MIN, SPRITE_RATE_WINDOW_MS,
  TRACK_EDGE_PADDING_PX, WRONG_ANSWER_LOCKOUT_MS,
} from "./constants";
import type { ArenaEventDecl } from "./declarations";
import { jumpEventDurationMs, scoreJumpEntrant } from "./fieldJump";
import type { LoadedRacer } from "./gameTypes";
import { recentAnswerRate, type Impulse } from "./raceEngine";
import { mulberry32 } from "./rng";

interface Props {
  event: ArenaEventDecl;
  challenge: ArenaChallenge;
  difficulty: string;
  raceSeed: number;
  lanes: LoadedRacer[];
  laneOffset?: number;
  humanLaneIndex: number;
  /** Accepted for call-site symmetry with RaceScreen; field events have no
   *  ghost lanes in v1 — hot-seat jumps run in sequence, as real ones do. */
  ghostLogs?: (Impulse[] | null)[];
  runLabel: string;
  onDone: (humanLog: Impulse[]) => void;
}

type JumpPhase = "countdown" | "running";

/** Where the take-off board sits across the lane (fraction of usable width). */
const BOARD_FRACTION = 0.55;

export default function JumpScreen({
  event, challenge, difficulty, raceSeed, lanes, laneOffset = 0,
  runLabel, onDone,
}: Props) {
  const [phase, setPhase] = useState<JumpPhase>("countdown");
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const [question, setQuestion] = useState<{ prompt: string; answer: string } | null>(null);
  const [givenAnswer, setGivenAnswer] = useState("");
  const [lockedOut, setLockedOut] = useState(false);
  const [attemptNow, setAttemptNow] = useState(0);
  const [inWindow, setInWindow] = useState(false);
  const [windowLeft, setWindowLeft] = useState(0);
  // Live per-lane attempt distances so far — recomputed from the logs on a
  // slow tick; the referee recomputes from scratch at the end anyway.
  const [liveAttempts, setLiveAttempts] = useState<number[][]>(
    () => lanes.map(() => []));

  const gunPerfRef = useRef<number | null>(null);
  const humanLogRef = useRef<Impulse[]>([]);
  const rngRef = useRef(mulberry32(raceSeed));
  const doneRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const laneElsRef = useRef<(HTMLDivElement | null)[]>([]);
  const spriteElsRef = useRef<(HTMLDivElement | null)[]>([]);

  const totalMs = useMemo(() => jumpEventDurationMs(event), [event]);
  const windowMs = (event.attempt_window_s ?? 0) * 1000;
  const attempts = event.attempts ?? 0;
  const cycleMs = attempts > 0 ? totalMs / attempts : 1;

  const laneLogs = useMemo<Impulse[][]>(() =>
    lanes.map((lane, i) => lane.kind === "bot"
      ? botImpulseLog(lane.botRung ?? "steady", raceSeed, laneOffset + i, totalMs)
      : humanLogRef.current),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [raceSeed]);

  const raceClock = useCallback(() =>
    gunPerfRef.current === null ? null : performance.now() - gunPerfRef.current,
  []);

  // Countdown → gun.
  useEffect(() => {
    if (phase !== "countdown") return;
    if (countdown <= 0) {
      gunPerfRef.current = performance.now();
      setQuestion(challenge.generate(rngRef.current, difficulty));
      setPhase("running");
      return;
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, countdown, challenge, difficulty]);

  const finish = useCallback(() => {
    if (!doneRef.current) {
      doneRef.current = true;
      onDone(humanLogRef.current);
    }
  }, [onDone]);

  // The schedule clock: attempt index, window state, live scores, the end.
  useEffect(() => {
    if (phase !== "running") return;
    const interval = setInterval(() => {
      const t = raceClock();
      if (t === null) return;
      if (t >= totalMs) { finish(); return; }
      const idx = Math.min(Math.floor(t / cycleMs), attempts - 1);
      const within = t - idx * cycleMs;
      setAttemptNow(idx);
      setInWindow(within < windowMs);
      setWindowLeft(Math.max(0, (windowMs - within) / 1000));
      setLiveAttempts(lanes.map((lane, i) =>
        scoreJumpEntrant(event, lane.stats, lane.handicap,
          laneLogs[i].filter((imp) => imp.at <= t),
          raceSeed, laneOffset + i).attempts));
    }, 150);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, raceClock, totalMs, cycleMs, windowMs, attempts, finish]);

  // The lane driver: approach during the window, leap + land after the
  // buzzer, walk back during the rest. Same engine primitives as the track.
  useEffect(() => {
    lanes.forEach((lane, i) => {
      const pet = getPet(lane.storeId);
      const petEl = spriteElsRef.current[i];
      const laneEl = laneElsRef.current[i];
      if (!pet || !petEl || !laneEl) return;
      pet.instance.petEl = petEl;
      pet.instance.stageEl = laneEl;
      pet.instance.x = TRACK_EDGE_PADDING_PX;
      pet.instance.y = 0;
      pet.facing = 1;
      const df = getDisplayFrame();
      petEl.style.backgroundImage = `url('${pet.sheetUrl}')`;
      petEl.style.backgroundSize = `${pet.sheetCols * df}px ${pet.sheetRows * df}px`;
      setAnim(pet, lane.racingPose, { force: true });
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

        const usable = Math.max(
          laneEl.clientWidth - ARENA_PET_DISPLAY_SIZE_PX - 2 * TRACK_EDGE_PADDING_PX, 1);
        const boardX = TRACK_EDGE_PADDING_PX + BOARD_FRACTION * usable;
        const pitWidth = usable * (1 - BOARD_FRACTION);

        let rate = 1;
        if (t !== null && t < totalMs) {
          const idx = Math.min(Math.floor(t / cycleMs), attempts - 1);
          const within = t - idx * cycleMs;
          const log = laneLogs[i];
          if (within < windowMs) {
            // Approach: creep toward the board as the window elapses; tempo
            // (frame rate) shows the answering, the leap will show the charge.
            pet.instance.x = TRACK_EDGE_PADDING_PX
              + (within / windowMs) * (boardX - TRACK_EDGE_PADDING_PX);
            if (pet.anim !== lane.racingPose) setAnim(pet, lane.racingPose);
            rate = Math.min(Math.max(
              recentAnswerRate(log, t, SPRITE_RATE_WINDOW_MS),
              SPRITE_RATE_MIN), SPRITE_RATE_MAX);
          } else {
            // The leap: land at the measured distance for THIS attempt.
            const scored = scoreJumpEntrant(event, lane.stats, lane.handicap,
              log.filter((imp) => imp.at <= idx * cycleMs + windowMs),
              raceSeed, laneOffset + i);
            const jumped = scored.attempts[idx] ?? 0;
            const landFrac = Math.min(jumped / JUMP_PIT_DISPLAY_MAX_M, 1);
            pet.instance.x = boardX + landFrac * pitWidth;
            const hopPose = lane.stats.poses.includes("jump") ? "jump" : lane.racingPose;
            if (pet.anim !== hopPose) setAnim(pet, hopPose);
          }
        }

        const anim = pet.anims[pet.anim];
        if (anim) {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lanes.map((l) => l.storeId).join(","), raceClock]);

  function submitAnswer(given: string) {
    if (phase !== "running" || !inWindow || lockedOut || !question) return;
    const t = raceClock();
    if (t === null) return;
    if (challenge.check(given, question.answer)) {
      humanLogRef.current.push({ at: t, quality: 1 });
      setQuestion(challenge.generate(rngRef.current, difficulty));
      setGivenAnswer("");
    } else {
      setGivenAnswer("");
      setLockedOut(true);
      setTimeout(() => {
        setLockedOut(false);
        inputRef.current?.focus();
      }, WRONG_ANSWER_LOCKOUT_MS);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">
          {event.emoji} {event.label} — {runLabel}
        </h2>
        <div className="flex items-baseline gap-3">
          <span className="mono text-sm" style={{ color: "var(--muted)" }}>
            attempt {Math.min(attemptNow + 1, attempts)} of {attempts}
            {inWindow && ` · ${windowLeft.toFixed(1)} s`}
          </span>
          {phase === "running" && (
            <button type="button" className="btn-ghost text-xs" onClick={finish}>
              🏳️ End event
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        {lanes.map((lane, i) => (
          <div key={lane.storeId}
            ref={(el) => { laneElsRef.current[i] = el; }}
            className="relative overflow-hidden rounded-lg"
            style={{
              height: LANE_HEIGHT_PX,
              background: "linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.06))",
              border: "1px solid rgba(255,255,255,0.08)",
            }}>
            <div className="absolute left-2 top-1 text-xs" style={{ color: "var(--muted)" }}>
              {lane.label}
              {lane.handicapName !== "none" && (
                <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                  style={{ background: "rgba(52,211,153,0.15)", color: "var(--green)" }}>
                  🚀 {lane.handicapName.replace(/_/g, " ")}
                </span>
              )}
            </div>
            {/* The take-off board and the landing pit. */}
            <div className="absolute bottom-0 top-0"
              style={{
                left: `calc(${TRACK_EDGE_PADDING_PX + ARENA_PET_DISPLAY_SIZE_PX}px + ${BOARD_FRACTION} * (100% - ${ARENA_PET_DISPLAY_SIZE_PX + 2 * TRACK_EDGE_PADDING_PX}px))`,
                width: 4,
                background: "rgba(255,255,255,0.35)",
              }} />
            <div className="absolute bottom-0 right-0 top-0"
              style={{
                width: `${(1 - BOARD_FRACTION) * 55}%`,
                background: "rgba(210,180,140,0.08)",
              }} />
            <div className="mono absolute right-2 top-1 text-[10px] tabular-nums"
              style={{ color: "var(--muted)" }}>
              {(liveAttempts[i] ?? []).map((d) => d.toFixed(1)).join(" · ") || "—"}
              {(liveAttempts[i] ?? []).length > 0 &&
                ` · best ${Math.max(...liveAttempts[i]).toFixed(1)} m`}
            </div>
            <div
              ref={(el) => { spriteElsRef.current[i] = el; }}
              className="absolute"
              style={{
                bottom: 4, left: 0,
                width: "var(--pet-display-size, 96px)",
                height: "var(--pet-display-size, 96px)",
                backgroundRepeat: "no-repeat",
                backgroundPosition: "0 0",
              }} />
          </div>
        ))}
      </div>

      {phase === "countdown" && (
        <div className="card p-6 text-center text-5xl font-bold">
          {countdown > 0 ? countdown : "GO!"}
        </div>
      )}

      {phase === "running" && (inWindow ? (
        question && (
          <div className="card p-4 text-center">
            {challenge.inputKind === "tap" ? (
              <button type="button" className="btn w-full py-8 text-3xl"
                onPointerDown={() => submitAnswer("")}>
                {question.prompt}
              </button>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); submitAnswer(givenAnswer); }}
                className="flex flex-col items-center gap-3">
                <div className="text-4xl font-bold">
                  {challenge.inputKind === "numeric"
                    ? `${question.prompt} = ?` : question.prompt}
                </div>
                <div className="flex gap-2">
                  <input ref={inputRef} autoFocus
                    inputMode={challenge.inputKind === "numeric" ? "numeric" : "text"}
                    value={givenAnswer} disabled={lockedOut}
                    onChange={(e) => setGivenAnswer(e.target.value)}
                    className={`${challenge.inputKind === "numeric" ? "w-32" : "w-64"} rounded-lg border bg-transparent px-3 py-2 text-center text-2xl`}
                    style={lockedOut ? { borderColor: "#f87171" } : undefined} />
                  <button type="submit" className="btn" disabled={lockedOut}>Go</button>
                </div>
                {lockedOut && (
                  <div className="text-sm" style={{ color: "#f87171" }}>
                    Not quite — take a breath…
                  </div>
                )}
              </form>
            )}
          </div>
        )
      ) : (
        <div className="card p-6 text-center text-2xl">
          🦘 Jump! …{attemptNow + 1 < attempts
            ? ` next run-up in a moment`
            : ` measuring…`}
        </div>
      ))}
    </div>
  );
}
