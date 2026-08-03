"use client";

/**
 * RoomLobby — the room SESSION container (SPEC_PET_ARENA_ROOMS R1+R2): owns
 * the one EventSource, the server-corrected clock, and the phase flow
 * lobby → countdown → race → result. The transport client lives here (§4.2):
 * reconnection and Last-Event-ID are the browser's own; URLs come from the
 * api.ts adapter, never minted here.
 *
 * During the race, `tick` events feed RemoteLane adapters (§3.4) that the
 * race screen's track reads; the `result` event is the server referee's
 * word, and whatever the screen drew, that is the finish order shown.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  arenaRoomStreamUrl, arenaWatchUrl, startArenaRoom,
  type ArenaRoomSnapshot, type ArenaTickPosition,
} from "@/lib/api";
import RoomRaceScreen, { RemoteLane } from "./RoomRaceScreen";

const COUNTDOWN_RENDER_TICK_MS = 200;
const MEDALS = ["🥇", "🥈", "🥉"];

interface Props {
  code: string;
  token: string;
  isHost: boolean;
  myLane: number;
  initialRoom: ArenaRoomSnapshot;
  onLeave: () => void;
}

export default function RoomLobby({
  code, token, isHost, myLane, initialRoom, onLeave,
}: Props) {
  const [room, setRoom] = useState<ArenaRoomSnapshot>(initialRoom);
  const [closed, setClosed] = useState<string | null>(null);
  const [standings, setStandings] = useState<ArenaTickPosition[] | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [countdownLeft, setCountdownLeft] = useState<number | null>(null);

  // Server clock offset (server_now − client now), refreshed per snapshot
  // and per tick — five devices, one clock (§2.3).
  const clockOffsetRef = useRef(0);
  const remoteLanesRef = useRef<Map<number, RemoteLane>>(new Map());
  const roomRef = useRef(room);
  roomRef.current = room;

  useEffect(() => {
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
      } catch { /* a malformed frame is dropped; the next event corrects */ }
    };
    es.addEventListener("snapshot", applyRoom);
    es.addEventListener("player_joined", applyRoom);
    es.addEventListener("countdown", applyRoom);
    es.addEventListener("tick", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const gun = roomRef.current.countdown_ends_at;
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
        if (roomRef.current.state !== "racing") {
          setRoom((r) => ({ ...r, state: "racing" }));
        }
      } catch { /* next tick corrects */ }
    });
    es.addEventListener("result", (e: MessageEvent) => {
      try {
        setStandings(JSON.parse(e.data).standings);
        setRoom((r) => ({ ...r, state: "finished" }));
      } catch { /* the room_closed reap will end the session regardless */ }
    });
    es.addEventListener("room_closed", (e: MessageEvent) => {
      let reason = "closed";
      try { reason = JSON.parse(e.data).reason ?? reason; } catch { /* default */ }
      setClosed(reason);
      es.close();
    });
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, myLane]);

  useEffect(() => {
    if (room.state !== "countdown" || room.countdown_ends_at === null) {
      setCountdownLeft(null);
      return;
    }
    const iv = setInterval(() => {
      const serverNow = Date.now() / 1000 + clockOffsetRef.current;
      setCountdownLeft(Math.max(0, room.countdown_ends_at! - serverNow));
    }, COUNTDOWN_RENDER_TICK_MS);
    return () => clearInterval(iv);
  }, [room.state, room.countdown_ends_at]);

  const raceClock = useMemo(() => () => {
    const gun = roomRef.current.countdown_ends_at;
    if (gun === null) return 0;
    return Math.max(0, (Date.now() / 1000 + clockOffsetRef.current - gun) * 1000);
  }, []);

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard denied — the code is on screen to copy by hand */ }
  };

  if (closed) {
    return (
      <div className="card flex flex-col gap-3 p-4">
        <h2 className="text-xl font-semibold">🚪 The room closed</h2>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          {closed === "idle"
            ? "Nobody raced for a while, so the room was tidied away."
            : "This room has ended."}
        </p>
        <button type="button" className="btn self-start" onClick={onLeave}>
          ← Back to the arena
        </button>
      </div>
    );
  }

  // The referee has spoken (§3.4: the result is the server's, always).
  if (standings !== null) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">🏁 Race results</h2>
        <div className="card flex flex-col gap-2 p-4">
          {standings.map((p, i) => (
            <div key={p.lane}
              className="flex items-baseline justify-between border-b border-white/5 pb-2 last:border-b-0">
              <div className="flex items-baseline gap-2">
                <span className="text-2xl">{MEDALS[i] ?? `#${i + 1}`}</span>
                <span className="font-semibold">
                  {p.pet_label}{p.lane === myLane ? " (you)" : ""}
                </span>
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
          <div className="pt-1 text-xs" style={{ color: "var(--muted)" }}>
            Scored by the referee from every player&apos;s answer log — same
            questions in every lane.
          </div>
        </div>
        <button type="button" className="btn self-start" onClick={onLeave}>
          ← Back to the arena
        </button>
      </div>
    );
  }

  // The gun has fired (locally past the broadcast end, or the first tick
  // arrived) — the race screen takes over.
  const racing = room.state === "racing"
    || (room.state === "countdown" && countdownLeft !== null && countdownLeft <= 0);
  if (racing) {
    return (
      <RoomRaceScreen code={code} token={token} room={room} myLane={myLane}
        raceClock={raceClock} remoteLanes={remoteLanesRef.current} />
    );
  }

  const seatsLeft = room.max_players - room.players.length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">🌐 Online race — lobby</h2>
        <button type="button" className="btn-ghost" onClick={onLeave}>
          ← Leave
        </button>
      </div>

      <div className="card flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm" style={{ color: "var(--muted)" }}>
            Room code — tell your friend:
          </span>
          <span className="mono rounded px-2 py-1 text-lg font-bold"
            style={{ background: "rgba(99,102,241,0.15)" }}>
            {code}
          </span>
          <button type="button" className="btn-ghost" onClick={copyCode}>
            {copied ? "✓ Copied" : "📋 Copy"}
          </button>
        </div>
        <div className="text-xs" style={{ color: "var(--muted)" }}>
          {room.event_key.replace(/_/g, " ")} · {room.challenge_key} ·{" "}
          {room.difficulty.replace(/_/g, " ")} · every lane sees the same questions
        </div>
        {/* R3 — the watchable part: one link, no account needed, dies with
            the room. */}
        <div className="flex flex-wrap items-center gap-2 text-xs"
          style={{ color: "var(--muted)" }}>
          <span>📺 Anyone can watch:</span>
          <a className="mono underline" href={arenaWatchUrl(code)}
            target="_blank" rel="noreferrer">
            {arenaWatchUrl(code)}
          </a>
        </div>
      </div>

      <div className="card flex flex-col gap-2 p-4">
        {room.players.map((p, i) => (
          <div key={`${p.pet_id}-${i}`}
            className="flex items-center justify-between border-b border-white/5 pb-2 last:border-b-0">
            <div className="flex items-center gap-2">
              <span className="text-2xl">🐾</span>
              <span className="font-semibold">
                {p.pet_label}{i === myLane ? " (you)" : ""}
              </span>
              {p.is_host && (
                <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                  style={{ background: "rgba(99,102,241,0.2)" }}>
                  HOST
                </span>
              )}
            </div>
            {p.handicap_name !== "none" && (
              <span className="text-xs" style={{ color: "var(--green)" }}>
                🚀 {p.handicap_name.replace(/_/g, " ")}
              </span>
            )}
          </div>
        ))}
        {seatsLeft > 0 && room.state === "lobby" && (
          <div className="text-sm" style={{ color: "var(--muted)" }}>
            {seatsLeft} more can join…
          </div>
        )}
      </div>

      {room.state === "lobby" && (
        isHost ? (
          <button type="button" className="btn self-start px-8 py-3 text-lg"
            onClick={async () => {
              setStartError(null);
              try { await startArenaRoom(code, token); }
              catch (e) { setStartError(e instanceof Error ? e.message : "Could not start"); }
            }}>
            🏟️ Start the race
          </button>
        ) : (
          <div className="text-sm" style={{ color: "var(--muted)" }}>
            Waiting for the host to start…
          </div>
        )
      )}
      {startError && (
        <div className="text-sm" style={{ color: "#f87171" }}>{startError}</div>
      )}

      {room.state === "countdown" && countdownLeft !== null && (
        <div className="card p-6 text-center text-5xl font-bold">
          {Math.ceil(countdownLeft) > 0 ? Math.ceil(countdownLeft) : "GO!"}
        </div>
      )}
    </div>
  );
}
