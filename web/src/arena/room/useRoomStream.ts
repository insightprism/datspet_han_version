"use client";

/**
 * useRoomStream — THE room transport client (§4.2, F14's de-dup): one
 * EventSource, the server-corrected clock, the countdown, the remote-lane
 * adapters, and the standings, consumed identically by the player session
 * (RoomLobby) and the spectator page (SpectatorView). A fix to the clock
 * formula or an event handler lands once, here.
 *
 * Reconnection and Last-Event-ID are the browser's own (EventSource resends
 * the header); URLs come from the api.ts adapter, never minted here.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  arenaRoomStreamUrl, getArenaRoom,
  type ArenaRoomSnapshot, type ArenaTickPosition,
} from "@/lib/api";
import { COUNTDOWN_RENDER_TICK_MS } from "../constants";
import type { Impulse, LaneProgress } from "../raceEngine";

/** Other players' pets render purely from the stream (§3.4): the adapter
 *  satisfies the track's LaneProgress and is stepped by server ticks. */
export class RemoteLane implements LaneProgress {
  distanceM = 0;
  finished = false;
  finishMs: number | null = null;
  readonly atHurdle = false;
  consume(_log: Impulse[], _uptoMs: number): void {
    /* fed by applyTick, never by impulses */
  }
  applyTick(distanceM: number, finished: boolean, finishMs: number | null): void {
    this.distanceM = distanceM;
    this.finished = finished;
    this.finishMs = finishMs;
  }
}

export interface RoomStreamState {
  room: ArenaRoomSnapshot | null;
  standings: ArenaTickPosition[] | null;
  /** The room_closed reason, or null while the stream lives. */
  closed: string | null;
  /** True when the room could not be found at all (spectator deep link). */
  notFound: boolean;
  /** Race clock in ms since the gun, server-corrected. */
  raceClock: () => number;
  countdownLeft: number | null;
  remoteLanes: Map<number, RemoteLane>;
}

export function useRoomStream(
  code: string,
  opts: { myLane: number | null; initialRoom?: ArenaRoomSnapshot },
): RoomStreamState {
  const { myLane, initialRoom } = opts;
  const [room, setRoom] = useState<ArenaRoomSnapshot | null>(initialRoom ?? null);
  const [standings, setStandings] = useState<ArenaTickPosition[] | null>(
    initialRoom?.standings ?? null);
  const [closed, setClosed] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [countdownLeft, setCountdownLeft] = useState<number | null>(null);

  // Server clock offset (server_now − client now), refreshed per snapshot
  // and per tick — five devices, one clock (§2.3).
  const clockOffsetRef = useRef(0);
  const remoteLanesRef = useRef<Map<number, RemoteLane>>(new Map());
  const roomRef = useRef<ArenaRoomSnapshot | null>(room);
  roomRef.current = room;

  // F6 — adapters exist for the whole roster the moment we know it, never
  // minted lazily by a consumer: a lane created outside this map would
  // receive no ticks and freeze a rival at 0 m for the race.
  const ensureAdapters = (snapshot: ArenaRoomSnapshot) => {
    snapshot.players.forEach((_, lane) => {
      if (lane === myLane) return;
      if (!remoteLanesRef.current.has(lane)) {
        remoteLanesRef.current.set(lane, new RemoteLane());
      }
    });
  };

  // Initial snapshot by GET when the caller has none (a spectator link);
  // the stream keeps it live either way.
  useEffect(() => {
    if (initialRoom) {
      ensureAdapters(initialRoom);
      return;
    }
    let cancelled = false;
    getArenaRoom(code)
      .then((r) => {
        if (cancelled) return;
        ensureAdapters(r);
        setRoom(r);
        if (r.standings) setStandings(r.standings);
      })
      .catch(() => { if (!cancelled) setNotFound(true); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  useEffect(() => {
    if (notFound) return;
    const es = new EventSource(arenaRoomStreamUrl(code));
    const applyRoom = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.room) {
          clockOffsetRef.current = data.room.server_now - Date.now() / 1000;
          ensureAdapters(data.room);
          setRoom(data.room);
          // A late arrival's snapshot carries a finished race's standings.
          if (data.room.standings) setStandings(data.room.standings);
        }
      } catch { /* a malformed frame is dropped; the next event corrects */ }
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
          if (pos.lane === myLane) continue;
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
      } catch { /* the room_closed reap ends the session regardless */ }
    });
    es.addEventListener("room_closed", (e: MessageEvent) => {
      let reason = "closed";
      try { reason = JSON.parse(e.data).reason ?? reason; } catch { /* default */ }
      setClosed(reason);
      es.close();
    });
    es.onerror = () => { if (roomRef.current === null) setNotFound(true); };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, myLane, notFound]);

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
  }, [room?.state, room?.countdown_ends_at]);   // eslint-disable-line react-hooks/exhaustive-deps

  const raceClock = useMemo(() => () => {
    const gun = roomRef.current?.countdown_ends_at ?? null;
    if (gun === null) return 0;
    return Math.max(0, (Date.now() / 1000 + clockOffsetRef.current - gun) * 1000);
  }, []);

  return { room, standings, closed, notFound, raceClock, countdownLeft,
           remoteLanes: remoteLanesRef.current };
}
