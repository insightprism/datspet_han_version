"use client";

/**
 * RoomRaceScreen — SPEC_PET_ARENA_ROOMS R2: the live multi-device race.
 *
 * The §3.4 authority split, exactly: MY pet advances locally the instant I
 * answer (the same LaneIntegrator the solo game drives — a correct answer
 * must move something NOW), while every OTHER lane is a RemoteLane adapter
 * fed by the server's 10 Hz ticks; ArenaTrack's chase smoothing turns those
 * steps into the same continuous motion local lanes get. The finish order on
 * screen is provisional — the server's `result` event is the referee.
 *
 * Impulses batch up every IMPULSE_BATCH_MS (§3.3), each carrying its own
 * race-clock timestamp, so batching costs no fidelity. Questions are
 * index-seeded off the ROOM's one seed (§8.3 fairness — every player's
 * question #i at a rung is identical across devices). Hurdle gates work
 * unchanged: the gate is in the integrator, the harder amber question is a
 * screen concern, and a room log stays replay-exact.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { postArenaImpulses, type ArenaRoomSnapshot } from "@/lib/api";
import { removePet } from "@/pet";
import ArenaTrack, { type TrackLane } from "../ArenaTrack";
import { judgeAnswer } from "../challenges/answerRules";
import ChallengePanel from "../ChallengePanel";
import {
  CHALLENGES, questionAt, harderRung, type ChallengeQuestion,
} from "../challenges/registry";
import {
  CRASH_FX_MS, HURDLE_CRASHES_TO_DQ, IMPULSE_BATCH_MS,
} from "../constants";
import { loadEvent } from "../declarations";
import type { LoadedRacer } from "../gameTypes";
import { loadRacer } from "../petLoader";
import {
  LaneIntegrator, type Impulse, type LaneProgress,
} from "../raceEngine";

/** Other players' pets, rendered purely from the stream (§3.4): the adapter
 *  satisfies the track's LaneProgress and is stepped by server ticks. */
export class RemoteLane implements LaneProgress {
  distanceM = 0;
  finished = false;
  finishMs: number | null = null;
  readonly atHurdle = false;
  consume(): void { /* fed by applyTick, never by impulses */ }
  applyTick(distanceM: number, finished: boolean, finishMs: number | null): void {
    this.distanceM = distanceM;
    this.finished = finished;
    this.finishMs = finishMs;
  }
}

interface Props {
  code: string;
  token: string;
  room: ArenaRoomSnapshot;
  myLane: number;
  /** Race clock in ms since the gun, from the server-corrected clock. */
  raceClock: () => number;
  /** Lane index → adapter; the session container feeds these from ticks. */
  remoteLanes: Map<number, RemoteLane>;
}

export default function RoomRaceScreen({
  code, token, room, myLane, raceClock, remoteLanes,
}: Props) {
  const event = useMemo(() => loadEvent(room.event_key), [room.event_key]);
  const challenge = CHALLENGES[room.challenge_key];
  const [racers, setRacers] = useState<(LoadedRacer | null)[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const myLogRef = useRef<Impulse[]>([]);
  const pendingRef = useRef<Impulse[]>([]);
  const myIntegratorRef = useRef<LaneIntegrator | null>(null);

  const [qIndex, setQIndex] = useState(0);
  const [answered, setAnswered] = useState({ right: 0, wrong: 0 });
  const [lockedUntil, setLockedUntil] = useState(0);
  const [typed, setTyped] = useState("");
  const [atGate, setAtGate] = useState(false);
  const [homeMs, setHomeMs] = useState<number | null>(null);
  // F3 — the screen must never silently diverge from the referee: when the
  // server holds fewer impulses than we sent (rate ceiling, lost batches),
  // say so instead of letting the child watch a win the referee scores as a
  // loss.
  const [refereeGap, setRefereeGap] = useState(0);
  // Rev.11 — same rules online as on the sofa: wrong at a gate is a crash,
  // the third disqualifies THIS lane (input locks; the referee still ranks
  // the distance covered — a DQ is a screen outcome, §7.4).
  const crashCountRef = useRef(0);
  const [crashCount, setCrashCount] = useState(0);
  const [disqualified, setDisqualified] = useState(false);
  const crashFxRefs = useRef<Map<number, { current: number }>>(new Map());

  // Load every lane's pet — mine through the owner routes, the others
  // through the room-scoped routes (§4.3).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!event) return;
      try {
        // A REMOTE lane whose assets fail (pet deleted mid-race, a flaky
        // fetch) must not kill the race: it just isn't drawn — the server
        // still scores it and it appears in the result. MY lane failing is
        // fatal: there is no race to run without my own pet.
        const loaded = await Promise.all(room.players.map((p, i) => loadRacer({
          petId: p.pet_id,
          storeId: `${p.pet_id}#room${i}`,
          label: i === myLane ? `You — ${p.pet_label}` : p.pet_label,
          kind: i === myLane ? "human" : "ghost",
          handicapName: p.handicap_name,
          roomCode: i === myLane ? undefined : code,
        }, event).catch(() => null)));
        if (cancelled) return;
        const mine = loaded[myLane];
        if (!mine) {
          setLoadError("Could not fetch your pet's sprite sheet.");
          return;
        }
        myIntegratorRef.current = new LaneIntegrator(
          event, mine.stats, mine.handicap, room.question_seed, myLane);
        setRacers(loaded);
      } catch {
        if (!cancelled) setLoadError("Could not fetch your pet's sprite sheet.");
      }
    })();
    return () => {
      cancelled = true;
      room.players.forEach((p, i) => removePet(`${p.pet_id}#room${i}`));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event, code]);

  // §3.3 — the uploader: whatever accumulated since the last batch, with
  // its own timestamps. A failed batch stays pending and rides the next one.
  useEffect(() => {
    const iv = setInterval(async () => {
      if (pendingRef.current.length === 0) return;
      const batch = pendingRef.current.splice(0, pendingRef.current.length);
      try {
        const resp = await postArenaImpulses(code, token,
          batch.map((i) => ({ at: i.at, quality: i.quality ?? 1 })));
        // Everything sent minus everything still pending should be on the
        // server; any shortfall is answers the referee will never count.
        const delivered = myLogRef.current.length - pendingRef.current.length;
        setRefereeGap(Math.max(0, delivered - resp.total));
      } catch {
        pendingRef.current.unshift(...batch);
      }
    }, IMPULSE_BATCH_MS);
    return () => clearInterval(iv);
  }, [code, token]);

  // The gate poll (Rev.9): the harder amber question while parked.
  useEffect(() => {
    const iv = setInterval(() => {
      const it = myIntegratorRef.current;
      if (!it) return;
      it.consume(myLogRef.current, raceClock());
      setAtGate(it.atHurdle);
      if (it.finished && homeMs === null) setHomeMs(it.finishMs);
    }, 100);
    return () => clearInterval(iv);
  }, [raceClock, homeMs]);

  const activeDifficulty = atGate
    ? harderRung(challenge, room.difficulty) : room.difficulty;
  const question: ChallengeQuestion = useMemo(
    () => questionAt(challenge, room.question_seed, qIndex, activeDifficulty),
    [challenge, room.question_seed, qIndex, activeDifficulty]);

  const submit = useCallback((answer: string) => {
    const now = performance.now();
    if (now < lockedUntil || homeMs !== null || disqualified) return;
    // The shared rules (F5's de-fork): the challenge's own check, the §8.5
    // choice burn, the §7.2 lockout, Rev.11 crashes — one definition for
    // solo and room alike. This screen's only difference is where a correct
    // answer goes: the local log AND the upload queue.
    const outcome = judgeAnswer(challenge, question, answer,
      { atGate, hurdledEvent: !!event?.hurdles_every_m });
    if (outcome.correct) {
      const impulse: Impulse = { at: raceClock(), quality: 1 };
      myLogRef.current.push(impulse);
      pendingRef.current.push(impulse);
      setAnswered((a) => ({ ...a, right: a.right + 1 }));
      setQIndex((i) => i + 1);
      setTyped("");
    } else {
      setAnswered((a) => ({ ...a, wrong: a.wrong + 1 }));
      if (outcome.crash) {
        crashCountRef.current += 1;
        setCrashCount(crashCountRef.current);
        const fx = crashFxRefs.current.get(myLane);
        if (fx) fx.current = performance.now() + CRASH_FX_MS;
        if (crashCountRef.current >= HURDLE_CRASHES_TO_DQ) {
          setDisqualified(true);
          setTyped("");
          return;
        }
      }
      if (outcome.burnQuestion) setQIndex((i) => i + 1);
      setLockedUntil(now + outcome.lockoutMs);
      setTyped("");
    }
  }, [challenge, question, lockedUntil, homeMs, disqualified, atGate, event,
      myLane, raceClock]);

  const trackLanes: TrackLane[] = useMemo(() => {
    if (!racers) return [];
    return racers.flatMap((racer, i) => {
      if (racer === null) return [];
      let fx = crashFxRefs.current.get(i);
      if (!fx) {
        fx = { current: 0 };
        crashFxRefs.current.set(i, fx);
      }
      return [{
        storeId: racer.storeId,
        label: racer.label,
        handicapName: racer.handicapName,
        racingPose: racer.racingPose,
        hopPose: ["jump", "play"].find((p) => racer.stats.poses.includes(p)),
        fallenPose: ["sleep", "sit", "idle"].find(
          (p) => racer.stats.poses.includes(p)),
        crashFxRef: fx,
        integrator: i === myLane
          ? myIntegratorRef.current!
          : (remoteLanes.get(i) ?? new RemoteLane()),
        log: i === myLane ? myLogRef.current : [],
      }];
    });
  }, [racers, myLane, remoteLanes]);

  if (!event) return <div className="card p-4">Unknown event.</div>;
  if (loadError) return <div className="card p-4" style={{ color: "#f87171" }}>{loadError}</div>;
  if (!racers) return <div className="card p-4">Walking the athletes to the track…</div>;

  const locked = performance.now() < lockedUntil;
  const total = answered.right + answered.wrong;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">{event.emoji} {event.label} — live!</h2>
        {/* The limit is visible so the automatic ending never surprises
            anyone (§2.3) — a race that just stops reads as a bug. */}
        <span className="mono text-sm" style={{ color: "var(--muted)" }}>
          {(raceClock() / 1000).toFixed(1)} / {event.time_limit_s} s ·{" "}
          {answered.right} answered
          {total > 0 && ` · ${Math.round((answered.right / total) * 100)}% right`}
          {event.hurdles_every_m ? ` · 💥 ${crashCount}/${HURDLE_CRASHES_TO_DQ}` : ""}
        </span>
      </div>

      <ArenaTrack lanes={trackLanes} distanceM={event.distance_m}
        hurdlesEveryM={event.hurdles_every_m} raceClock={raceClock} />

      {refereeGap > 0 && (
        <div className="text-center text-xs" style={{ color: "#fbbf24" }}>
          ⚠ {refereeGap} of your answers didn&apos;t reach the referee — the
          standings come from what the referee saw.
        </div>
      )}

      {homeMs !== null ? (
        <div className="card p-4 text-center">
          🏁 You&apos;re home in {(homeMs / 1000).toFixed(1)} s! Watching the
          rest of the field — the referee calls it when everyone is in.
        </div>
      ) : disqualified ? (
        <div className="card p-4 text-center" style={{ color: "#f87171" }}>
          💥 Three crashes — you&apos;re out of this one. Your pet sits at{" "}
          {myIntegratorRef.current
            ? myIntegratorRef.current.distanceM.toFixed(0) : 0}{" "}
          m while the others finish.
        </div>
      ) : (
        <ChallengePanel
          challenge={challenge} question={question} atGate={atGate}
          lockedOut={locked} given={typed}
          onGivenChange={setTyped} onSubmit={submit}
        />
      )}
    </div>
  );
}
