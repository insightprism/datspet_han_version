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
import {
  CHALLENGES, questionAt, harderRung, type ChallengeQuestion,
} from "../challenges/registry";
import {
  HURDLE_JUMP_ACCENT, HURDLE_JUMP_ACCENT_BG, IMPULSE_BATCH_MS,
  WRONG_ANSWER_LOCKOUT_MS, WRONG_CHOICE_LOCKOUT_MS,
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
  const [racers, setRacers] = useState<LoadedRacer[] | null>(null);
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

  // Load every lane's pet — mine through the owner routes, the others
  // through the room-scoped routes (§4.3).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!event) return;
      try {
        const loaded = await Promise.all(room.players.map((p, i) => loadRacer({
          petId: p.pet_id,
          storeId: `${p.pet_id}#room${i}`,
          label: i === myLane ? `You — ${p.pet_label}` : p.pet_label,
          kind: i === myLane ? "human" : "ghost",
          handicapName: p.handicap_name,
          roomCode: i === myLane ? undefined : code,
        }, event)));
        if (cancelled) return;
        myIntegratorRef.current = new LaneIntegrator(
          event, loaded[myLane].stats, loaded[myLane].handicap,
          room.question_seed, myLane);
        setRacers(loaded);
      } catch {
        if (!cancelled) setLoadError("Could not fetch a racer's sprite sheet.");
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
        await postArenaImpulses(code, token,
          batch.map((i) => ({ at: i.at, quality: i.quality ?? 1 })));
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
    if (now < lockedUntil || homeMs !== null) return;
    const ok = challenge.inputKind === "tap"
      || answer.trim().toLowerCase() === question.answer.trim().toLowerCase();
    if (ok) {
      const impulse: Impulse = { at: raceClock(), quality: 1 };
      myLogRef.current.push(impulse);
      pendingRef.current.push(impulse);
      setAnswered((a) => ({ ...a, right: a.right + 1 }));
      setQIndex((i) => i + 1);
      setTyped("");
    } else {
      setAnswered((a) => ({ ...a, wrong: a.wrong + 1 }));
      setLockedUntil(now + (challenge.inputKind === "choice"
        ? WRONG_CHOICE_LOCKOUT_MS : WRONG_ANSWER_LOCKOUT_MS));
      setTyped("");
    }
  }, [challenge, question, lockedUntil, homeMs, raceClock]);

  const trackLanes: TrackLane[] = useMemo(() => {
    if (!racers) return [];
    return racers.map((racer, i) => ({
      storeId: racer.storeId,
      label: racer.label,
      handicapName: racer.handicapName,
      racingPose: racer.racingPose,
      hopPose: ["jump", "play"].find((p) => racer.stats.poses.includes(p)),
      integrator: i === myLane
        ? myIntegratorRef.current!
        : (remoteLanes.get(i) ?? new RemoteLane()),
      log: i === myLane ? myLogRef.current : [],
    }));
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
        <span className="mono text-sm" style={{ color: "var(--muted)" }}>
          {(raceClock() / 1000).toFixed(1)} s · {answered.right} answered
          {total > 0 && ` · ${Math.round((answered.right / total) * 100)}% right`}
        </span>
      </div>

      <ArenaTrack lanes={trackLanes} distanceM={event.distance_m}
        hurdlesEveryM={event.hurdles_every_m} raceClock={raceClock} />

      {homeMs !== null ? (
        <div className="card p-4 text-center">
          🏁 You&apos;re home in {(homeMs / 1000).toFixed(1)} s! Watching the
          rest of the field — the referee calls it when everyone is in.
        </div>
      ) : (
        <div className="card flex flex-col gap-3 p-4"
          style={atGate ? {
            border: `1px solid ${HURDLE_JUMP_ACCENT}`,
            background: HURDLE_JUMP_ACCENT_BG,
          } : undefined}>
          {atGate && (
            <div className="text-center text-sm font-semibold"
              style={{ color: HURDLE_JUMP_ACCENT }}>
              🚧 JUMP! A harder one clears the hurdle:
            </div>
          )}
          {challenge.inputKind === "tap" ? (
            <button type="button"
              className="w-full rounded-xl border py-6 text-3xl font-bold"
              style={atGate ? { borderColor: HURDLE_JUMP_ACCENT, color: HURDLE_JUMP_ACCENT }
                : { borderColor: "var(--accent)" }}
              onPointerDown={() => submit("")}>
              {atGate ? "TAP to JUMP!" : "TAP!"}
            </button>
          ) : (
            <>
              <div className="text-center text-4xl font-bold">{question.prompt}</div>
              {question.choices ? (
                <div className="flex justify-center gap-3">
                  {question.choices.map((c) => (
                    <button key={c} type="button" disabled={locked}
                      className="rounded-lg border px-8 py-3 text-2xl"
                      style={{
                        borderColor: atGate ? HURDLE_JUMP_ACCENT : "var(--accent)",
                        opacity: locked ? 0.4 : 1,
                        color: atGate ? HURDLE_JUMP_ACCENT : undefined,
                      }}
                      onClick={() => submit(c)}>
                      {c}
                    </button>
                  ))}
                </div>
              ) : (
                <form className="flex justify-center gap-2"
                  onSubmit={(e) => { e.preventDefault(); submit(typed); }}>
                  <input className="input mono w-40 text-center text-2xl"
                    value={typed} disabled={locked} autoFocus
                    onChange={(e) => setTyped(e.target.value)} />
                  <button type="submit" className="btn" disabled={locked}>Go</button>
                </form>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
