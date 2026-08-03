"use client";

/**
 * SpectatorView — SPEC_PET_ARENA_ROOMS R3: the watchable race. Anyone holding
 * the room URL sees the lobby fill, the countdown, every lane live, and the
 * referee's standings — and can do nothing else (§0.5: read-only; the stream
 * is the same one players get, minus the ability to send).
 *
 * Every lane is a RemoteLane fed by ticks — a spectator has no local
 * integrator because they have no impulses. Pets load through the
 * room-scoped asset routes (§4.3): the code is the capability, no account
 * exists, and the links die with the room (§6 — a shared link stops
 * working, which is the correct default).
 *
 * §14.4 (should spectators see the questions?) is an OPEN owner call — until
 * it is made, the race and the result are shown, the questions are not.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  arenaRoomStreamUrl, getArenaRoom,
  type ArenaRoomSnapshot, type ArenaTickPosition,
} from "@/lib/api";
import { removePet } from "@/pet";
import ArenaTrack, { type TrackLane } from "../ArenaTrack";
import { loadEvent } from "../declarations";
import type { LoadedRacer } from "../gameTypes";
import { loadRacer } from "../petLoader";
import { RemoteLane } from "./RoomRaceScreen";

const COUNTDOWN_RENDER_TICK_MS = 200;
/** Ticks feed lane adapters (refs), so nothing re-renders the header — this
 *  slow tick keeps the clock and the "live" state honest for the viewer. */
const SPECTATOR_RENDER_TICK_MS = 500;
const MEDALS = ["🥇", "🥈", "🥉"];

export default function SpectatorView({ code }: { code: string }) {
  const [room, setRoom] = useState<ArenaRoomSnapshot | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [closed, setClosed] = useState<string | null>(null);
  const [standings, setStandings] = useState<ArenaTickPosition[] | null>(null);
  const [racers, setRacers] = useState<(LoadedRacer | null)[] | null>(null);
  const [countdownLeft, setCountdownLeft] = useState<number | null>(null);

  const clockOffsetRef = useRef(0);
  const remoteLanesRef = useRef<Map<number, RemoteLane>>(new Map());
  const roomRef = useRef<ArenaRoomSnapshot | null>(null);
  roomRef.current = room;

  // Initial snapshot by plain GET, then the stream keeps it live.
  useEffect(() => {
    let cancelled = false;
    getArenaRoom(code)
      .then((r) => {
        if (cancelled) return;
        setRoom(r);
        if (r.standings) setStandings(r.standings);
      })
      .catch(() => { if (!cancelled) setNotFound(true); });
    return () => { cancelled = true; };
  }, [code]);

  useEffect(() => {
    if (notFound) return;
    const es = new EventSource(arenaRoomStreamUrl(code));
    const applyRoom = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.room) {
          clockOffsetRef.current = data.room.server_now - Date.now() / 1000;
          setRoom(data.room);
          // A late arrival's snapshot carries the finished race's standings.
          if (data.room.standings) setStandings(data.room.standings);
        }
      } catch { /* the next event corrects */ }
    };
    es.addEventListener("snapshot", applyRoom);
    es.addEventListener("player_joined", applyRoom);
    es.addEventListener("countdown", applyRoom);
    es.addEventListener("tick", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const gun = roomRef.current?.countdown_ends_at ?? null;
        if (gun !== null) {
          clockOffsetRef.current =
            gun + data.elapsed_ms / 1000 - Date.now() / 1000;
        }
        for (const pos of data.positions as ArenaTickPosition[]) {
          let lane = remoteLanesRef.current.get(pos.lane);
          if (!lane) {
            lane = new RemoteLane();
            remoteLanesRef.current.set(pos.lane, lane);
          }
          lane.applyTick(pos.distance_m, pos.finished, pos.finish_ms);
        }
        setRoom((r) => r && r.state !== "racing" ? { ...r, state: "racing" } : r);
      } catch { /* next tick corrects */ }
    });
    es.addEventListener("result", (e: MessageEvent) => {
      try {
        setStandings(JSON.parse(e.data).standings);
        setRoom((r) => r ? { ...r, state: "finished" } : r);
      } catch { /* the reap will close the stream regardless */ }
    });
    es.addEventListener("room_closed", (e: MessageEvent) => {
      let reason = "closed";
      try { reason = JSON.parse(e.data).reason ?? reason; } catch { /* default */ }
      setClosed(reason);
      es.close();
    });
    es.onerror = () => { if (roomRef.current === null) setNotFound(true); };
    return () => es.close();
  }, [code, notFound]);

  // Load every entered pet through the room-scoped routes once players exist.
  const playerKey = room?.players.map((p) => p.pet_id).join(",") ?? "";
  const event = useMemo(
    () => room ? loadEvent(room.event_key) : null, [room?.event_key]);
  useEffect(() => {
    if (!room || !event || room.players.length === 0) return;
    let cancelled = false;
    (async () => {
      const loaded = await Promise.all(room.players.map((p, i) => loadRacer({
        petId: p.pet_id,
        storeId: `${p.pet_id}#watch${i}`,
        label: p.pet_label,
        kind: "ghost",
        handicapName: p.handicap_name,
        roomCode: code,
      }, event).catch(() => null)));
      if (!cancelled) setRacers(loaded);
    })();
    return () => {
      cancelled = true;
      room.players.forEach((p, i) => removePet(`${p.pet_id}#watch${i}`));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerKey, event, code]);

  useEffect(() => {
    if (!room || room.state !== "countdown" || room.countdown_ends_at === null) {
      setCountdownLeft(null);
      return;
    }
    const iv = setInterval(() => {
      const serverNow = Date.now() / 1000 + clockOffsetRef.current;
      setCountdownLeft(Math.max(0, room.countdown_ends_at! - serverNow));
    }, COUNTDOWN_RENDER_TICK_MS);
    return () => clearInterval(iv);
  }, [room?.state, room?.countdown_ends_at]);

  // Re-render on a slow cadence while racing so the clock advances.
  const [, setRenderTick] = useState(0);
  useEffect(() => {
    if (room?.state !== "racing") return;
    const iv = setInterval(
      () => setRenderTick((t) => t + 1), SPECTATOR_RENDER_TICK_MS);
    return () => clearInterval(iv);
  }, [room?.state]);

  const raceClock = useMemo(() => () => {
    const gun = roomRef.current?.countdown_ends_at ?? null;
    if (gun === null) return 0;
    return Math.max(0, (Date.now() / 1000 + clockOffsetRef.current - gun) * 1000);
  }, []);

  const trackLanes: TrackLane[] = useMemo(() => {
    if (!racers) return [];
    return racers.flatMap((racer, i) => racer === null ? [] : [{
      storeId: racer.storeId,
      label: racer.label,
      handicapName: racer.handicapName,
      racingPose: racer.racingPose,
      hopPose: ["jump", "play"].find((p) => racer.stats.poses.includes(p)),
      integrator: (remoteLanesRef.current.get(i)
        ?? (() => {
          const lane = new RemoteLane();
          remoteLanesRef.current.set(i, lane);
          return lane;
        })()),
      log: [],
    }]);
  }, [racers]);

  if (notFound || closed) {
    return (
      <div className="card flex flex-col gap-2 p-4">
        <h2 className="text-xl font-semibold">🚪 Nothing to watch here</h2>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          This race has ended, or the link has expired — race links only live
          as long as the race does.
        </p>
      </div>
    );
  }

  if (!room || !event) {
    return <div className="card p-4">Finding the race…</div>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">
          {event.emoji} {event.label} — {room.state === "finished"
            ? "finished" : room.state === "lobby" ? "warming up" : "live"} 📺
        </h2>
        {room.state === "racing" && (
          <span className="mono text-sm" style={{ color: "var(--muted)" }}>
            {(raceClock() / 1000).toFixed(0)} s
          </span>
        )}
      </div>

      {standings !== null ? (
        <div className="card flex flex-col gap-2 p-4">
          {standings.map((p, i) => (
            <div key={p.lane}
              className="flex items-baseline justify-between border-b border-white/5 pb-2 last:border-b-0">
              <div className="flex items-baseline gap-2">
                <span className="text-2xl">{MEDALS[i] ?? `#${i + 1}`}</span>
                <span className="font-semibold">{p.pet_label}</span>
                {p.handicap_name !== "none" && (
                  <span className="text-xs" style={{ color: "var(--green)" }}>
                    🚀 {p.handicap_name.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <span className="mono">
                {p.finished && p.finish_ms !== null
                  ? `${(p.finish_ms / 1000).toFixed(1)} s`
                  : `${p.distance_m.toFixed(0)} m`}
              </span>
            </div>
          ))}
        </div>
      ) : trackLanes.length > 0 ? (
        <ArenaTrack lanes={trackLanes} distanceM={event.distance_m}
          hurdlesEveryM={event.hurdles_every_m} raceClock={raceClock} />
      ) : (
        <div className="card p-4 text-sm" style={{ color: "var(--muted)" }}>
          Waiting for the racers to line up…
        </div>
      )}

      {room.state === "lobby" && (
        <div className="card p-4 text-sm" style={{ color: "var(--muted)" }}>
          {room.players.length} in the lobby — the host starts the race.
        </div>
      )}
      {room.state === "countdown" && countdownLeft !== null && (
        <div className="card p-6 text-center text-5xl font-bold">
          {Math.ceil(countdownLeft) > 0 ? Math.ceil(countdownLeft) : "GO!"}
        </div>
      )}
    </div>
  );
}
