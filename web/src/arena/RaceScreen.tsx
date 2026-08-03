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
import { judgeAnswer } from "./challenges/answerRules";
import {
  harderRung, questionAt, type ArenaChallenge,
} from "./challenges/registry";
import ChallengePanel from "./ChallengePanel";
import {
  COUNTDOWN_SECONDS, CRASH_FX_MS, GATE_POLL_MS, HURDLE_CRASHES_TO_DQ,
} from "./constants";
import type { ArenaEventDecl } from "./declarations";
import type { LoadedRacer, RunAccuracy } from "./gameTypes";
import { LaneIntegrator, type Impulse } from "./raceEngine";
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
  onDone: (humanLog: Impulse[], accuracy: RunAccuracy) => void;
}

type RunPhase = "countdown" | "racing" | "watching";

export default function RaceScreen({
  event, challenge, difficulty, raceSeed, lanes, laneOffset = 0,
  humanLaneIndex, ghostLogs, runLabel, onDone,
}: Props) {
  const [phase, setPhase] = useState<RunPhase>("countdown");
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const [qIndex, setQIndex] = useState(0);
  const [givenAnswer, setGivenAnswer] = useState("");
  const [lockedOut, setLockedOut] = useState(false);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [clockDisplay, setClockDisplay] = useState(0);
  const [finishedLanes, setFinishedLanes] = useState<Set<number>>(new Set());
  // Rev.9 — parked at a hurdle: the question is one rung harder, in the jump
  // color. Polled off the human lane's integrator.
  const [atHurdle, setAtHurdle] = useState(false);

  const gunPerfRef = useRef<number | null>(null);
  const humanLogRef = useRef<Impulse[]>([]);
  // Wrongs counted here; rights ARE the log length (§7.1).
  const wrongCountRef = useRef(0);
  // Rev.11: wrong answers AT a gate are crashes; three disqualify.
  const crashCountRef = useRef(0);
  const [crashCount, setCrashCount] = useState(0);
  const crashFxRefs = useRef(lanes.map(() => ({ current: 0 })));
  const dqRef = useRef(false);
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
      hopPose: ["jump", "play"].find((p) => lane.stats.poses.includes(p)),
      fallenPose: ["sleep", "sit", "idle"].find((p) => lane.stats.poses.includes(p)),
      crashFxRef: crashFxRefs.current[i],
      integrator: new LaneIntegrator(event, lane.stats, lane.handicap,
        raceSeed, laneOffset + i),
      log: laneLogs[i],
    })),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [raceSeed]);

  const raceClock = useCallback(() =>
    gunPerfRef.current === null ? null : performance.now() - gunPerfRef.current,
  []);

  // Rev.9 — questions are index-seeded: #i at rung d is identical for every
  // player, even when hurdle gates make their difficulty paths diverge (§8.3).
  const activeDifficulty = atHurdle ? harderRung(challenge, difficulty) : difficulty;
  const question = phase === "countdown"
    ? null
    : questionAt(challenge, raceSeed, qIndex, activeDifficulty);

  // Countdown → gun.
  useEffect(() => {
    if (phase !== "countdown") return;
    if (countdown <= 0) {
      gunPerfRef.current = performance.now();
      setPhase("racing");
      return;
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, countdown]);

  // The wall clock display + the event's time limit (§2.3 rooms-parity: a
  // wandered-off child must not hold the race open forever).
  useEffect(() => {
    if (phase === "countdown") return;
    const interval = setInterval(() => {
      const t = raceClock();
      if (t === null) return;
      setClockDisplay(t / 1000);
      setAtHurdle(trackLanes[humanLaneIndex]?.integrator.atHurdle ?? false);
      if (t >= event.time_limit_s * 1000 && !doneRef.current) {
        doneRef.current = true;
        onDone(humanLogRef.current,
          { right: humanLogRef.current.length, wrong: wrongCountRef.current,
            crashes: crashCountRef.current, disqualified: dqRef.current });
      }
    }, GATE_POLL_MS);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, raceClock, event.time_limit_s, onDone]);

  const finish = useCallback(() => {
    if (!doneRef.current) {
      doneRef.current = true;
      onDone(humanLogRef.current,
        { right: humanLogRef.current.length, wrong: wrongCountRef.current,
          crashes: crashCountRef.current, disqualified: dqRef.current });
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
    if (phase !== "racing" || lockedOut || dqRef.current || !question) return;
    const t = raceClock();
    if (t === null) return;
    // What the answer MEANS is the shared rules module's call — correctness
    // via the challenge's own check, the §8.5 choice burn, the §7.2 lockout,
    // and whether a gate crash happened. This screen owns what happens next.
    const outcome = judgeAnswer(challenge, question, given,
      { atGate: atHurdle, hurdledEvent: !!event.hurdles_every_m });
    if (outcome.correct) {
      humanLogRef.current.push({ at: t, quality: 1 });
      setAnsweredCount((n) => n + 1);
      setQIndex((i) => i + 1);
      setGivenAnswer("");
    } else {
      wrongCountRef.current += 1;
      // Rev.11 — a crash tumbles the pet, and the third disqualifies.
      if (outcome.crash) {
        crashCountRef.current += 1;
        setCrashCount(crashCountRef.current);
        const fx = crashFxRefs.current[humanLaneIndex];
        if (fx) fx.current = performance.now() + CRASH_FX_MS;
        if (crashCountRef.current >= HURDLE_CRASHES_TO_DQ) {
          // The third crash ends it — lock input NOW so nothing lands during
          // the tumble, show the fall, then to the results.
          dqRef.current = true;
          setLockedOut(true);
          setTimeout(finish, CRASH_FX_MS);
          return;
        }
      }
      if (outcome.burnQuestion) setQIndex((i) => i + 1);
      setGivenAnswer("");
      setLockedOut(true);
      setTimeout(() => {
        setLockedOut(false);
        inputRef.current?.focus();
      }, outcome.lockoutMs);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">
          {event.emoji} {event.label} — {runLabel}
        </h2>
        <div className="flex items-baseline gap-3">
          {/* The limit is visible so the automatic ending never surprises
              anyone — a race that just stops reads as a bug. */}
          <span className="mono text-sm" style={{ color: "var(--muted)" }}>
            {clockDisplay.toFixed(1)} / {event.time_limit_s} s · {answeredCount} answered
            {event.hurdles_every_m ? ` · 💥 ${crashCount}/${HURDLE_CRASHES_TO_DQ}` : ""}
          </span>
          {phase === "racing" && (
            <button type="button" className="btn-ghost text-xs" onClick={finish}>
              🏳️ End race
            </button>
          )}
        </div>
      </div>

      <ArenaTrack
        lanes={trackLanes}
        distanceM={event.distance_m}
        hurdlesEveryM={event.hurdles_every_m}
        raceClock={raceClock}
        onLaneFinish={onLaneFinish}
      />

      {phase === "countdown" && (
        <div className="card p-6 text-center text-5xl font-bold">
          {countdown > 0 ? countdown : "GO!"}
        </div>
      )}

      {phase === "racing" && question && (
        <ChallengePanel
          challenge={challenge} question={question} atGate={atHurdle}
          lockedOut={lockedOut} given={givenAnswer}
          onGivenChange={setGivenAnswer} onSubmit={submitAnswer}
          inputRef={inputRef}
        />
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
