"use client";

/**
 * RaceScreen — one running of one event (SPEC_PET_ARENA §7): the countdown,
 * the challenge panel, and the live track. The human's correct answers become
 * impulses; the bot's log is precomputed from the same seed (§7.3 — the event
 * cannot tell the difference); a ghost lane replays a recorded log (§7.4 —
 * hot-seat player 2 races player 1's actual run, not a simulation of it).
 *
 * §7.2: a wrong answer costs time (brief lockout), never distance, and the
 * pet never moves backwards. §8.3: the question sequence comes from the race
 * seed, so both hot-seat players face identical questions in identical order.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { botImpulseLog } from "./bot";
import type { ArenaChallenge } from "./challenges/registry";
import { COUNTDOWN_SECONDS, WRONG_ANSWER_LOCKOUT_MS } from "./constants";
import type { ArenaEventDecl } from "./declarations";
import type { LoadedRacer } from "./gameTypes";
import { LaneIntegrator, type Impulse } from "./raceEngine";
import { mulberry32 } from "./rng";
import ArenaTrack, { type TrackLane } from "./ArenaTrack";

interface Props {
  event: ArenaEventDecl;
  challenge: ArenaChallenge;
  difficulty: string;
  raceSeed: number;
  /** This run's lanes. `laneOffset` maps array position → canonical lane
   *  index, so a hot-seat solo run still integrates as canonical lane 0
   *  and the referee's numbers match what was on screen. */
  lanes: LoadedRacer[];
  laneOffset?: number;
  humanLaneIndex: number;
  /** Per lane: a recorded log for ghost lanes, null otherwise. */
  ghostLogs: (Impulse[] | null)[];
  runLabel: string;
  onDone: (humanLog: Impulse[]) => void;
}

type RunPhase = "countdown" | "racing" | "watching";

export default function RaceScreen({
  event, challenge, difficulty, raceSeed, lanes, laneOffset = 0,
  humanLaneIndex, ghostLogs, runLabel, onDone,
}: Props) {
  const [phase, setPhase] = useState<RunPhase>("countdown");
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const [question, setQuestion] = useState<{ prompt: string; answer: string } | null>(null);
  const [givenAnswer, setGivenAnswer] = useState("");
  const [lockedOut, setLockedOut] = useState(false);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [clockDisplay, setClockDisplay] = useState(0);
  const [finishedLanes, setFinishedLanes] = useState<Set<number>>(new Set());

  const gunPerfRef = useRef<number | null>(null);
  const humanLogRef = useRef<Impulse[]>([]);
  const rngRef = useRef(mulberry32(raceSeed));
  const doneRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Per-lane logs, fixed for the run: human appends live; bot precomputed
  // from the same seed and its CANONICAL lane; ghost replays the recording.
  const laneLogs = useMemo<Impulse[][]>(() =>
    lanes.map((lane, i) => {
      if (ghostLogs[i]) return ghostLogs[i]!;
      if (lane.kind === "bot") {
        return botImpulseLog(lane.botRung ?? "steady", raceSeed,
          laneOffset + i, event.time_limit_s * 1000);
      }
      return humanLogRef.current;
    }),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [raceSeed]);

  const trackLanes = useMemo<TrackLane[]>(() =>
    lanes.map((lane, i) => ({
      storeId: lane.storeId,
      label: lane.label,
      handicapName: lane.handicapName,
      racingPose: lane.racingPose,
      integrator: new LaneIntegrator(event, lane.stats, lane.handicap,
        raceSeed, laneOffset + i),
      log: laneLogs[i],
    })),
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
      setPhase("racing");
      return;
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, countdown, challenge, difficulty]);

  // The wall clock display + the event's time limit (§2.3 rooms-parity: a
  // wandered-off child must not hold the race open forever).
  useEffect(() => {
    if (phase === "countdown") return;
    const interval = setInterval(() => {
      const t = raceClock();
      if (t === null) return;
      setClockDisplay(t / 1000);
      if (t >= event.time_limit_s * 1000 && !doneRef.current) {
        doneRef.current = true;
        onDone(humanLogRef.current);
      }
    }, 100);
    return () => clearInterval(interval);
  }, [phase, raceClock, event.time_limit_s, onDone]);

  const finish = useCallback(() => {
    if (!doneRef.current) {
      doneRef.current = true;
      onDone(humanLogRef.current);
    }
  }, [onDone]);

  const onLaneFinish = useCallback((laneIdx: number) => {
    setFinishedLanes((prev) => {
      const next = new Set(prev);
      next.add(laneIdx);
      return next;
    });
  }, []);

  // Every lane home → the run is over.
  useEffect(() => {
    if (phase === "countdown") return;
    if (finishedLanes.size === lanes.length) finish();
    else if (finishedLanes.has(humanLaneIndex) && phase === "racing") {
      setPhase("watching");
    }
  }, [finishedLanes, lanes.length, humanLaneIndex, phase, finish]);

  function submitAnswer(given: string) {
    if (phase !== "racing" || lockedOut || !question) return;
    const t = raceClock();
    if (t === null) return;
    if (challenge.check(given, question.answer)) {
      humanLogRef.current.push({ at: t, quality: 1 });
      setAnsweredCount((n) => n + 1);
      setQuestion(challenge.generate(rngRef.current, difficulty));
      setGivenAnswer("");
    } else {
      // §7.2 — time cost, never distance: no impulse, brief lockout.
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
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-semibold">
          {event.emoji} {event.label} — {runLabel}
        </h2>
        <span className="mono text-sm" style={{ color: "var(--muted)" }}>
          {clockDisplay.toFixed(1)} s · {answeredCount} answered
        </span>
      </div>

      <ArenaTrack
        lanes={trackLanes}
        distanceM={event.distance_m}
        raceClock={raceClock}
        onLaneFinish={onLaneFinish}
      />

      {phase === "countdown" && (
        <div className="card p-6 text-center text-5xl font-bold">
          {countdown > 0 ? countdown : "GO!"}
        </div>
      )}

      {phase === "racing" && question && (
        <div className="card p-4 text-center">
          {challenge.inputKind === "tap" ? (
            <button
              type="button"
              className="btn w-full py-8 text-3xl"
              onPointerDown={() => submitAnswer("")}
            >
              {question.prompt}
            </button>
          ) : (
            <form
              onSubmit={(e) => { e.preventDefault(); submitAnswer(givenAnswer); }}
              className="flex flex-col items-center gap-3"
            >
              <div className="text-4xl font-bold">
                {challenge.inputKind === "numeric"
                  ? `${question.prompt} = ?`
                  : question.prompt}
              </div>
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  autoFocus
                  inputMode={challenge.inputKind === "numeric" ? "numeric" : "text"}
                  value={givenAnswer}
                  disabled={lockedOut}
                  onChange={(e) => setGivenAnswer(e.target.value)}
                  className={`${challenge.inputKind === "numeric" ? "w-32" : "w-64"} rounded-lg border bg-transparent px-3 py-2 text-center text-2xl`}
                  style={lockedOut ? { borderColor: "#f87171" } : undefined}
                />
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
      )}

      {phase === "watching" && (
        <div className="card flex items-center justify-between p-4">
          <span>🏁 You're home! Watching the rest of the field…</span>
          <button type="button" className="btn" onClick={finish}>
            Skip to results
          </button>
        </div>
      )}
    </div>
  );
}
