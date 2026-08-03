"use client";

/**
 * RoomLobby — SPEC_PET_ARENA_ROOMS R1: five devices in a lobby, seeing each
 * other appear the moment they join. The transport client lives here (§4.2):
 * one EventSource on the room's stream, reconnection and Last-Event-ID are
 * the browser's own (EventSource resends the header itself); URLs come from
 * the api.ts adapter, never minted here.
 *
 * Other players render as pet label + paw glyph, not a thumbnail: sheets are
 * owner-scoped until R3's room-scoped asset route, and the lobby must not
 * pretend otherwise. R2 replaces the "racing" placeholder with the race.
 */

import { useEffect, useRef, useState } from "react";
import {
  arenaRoomStreamUrl, startArenaRoom, type ArenaRoomSnapshot,
} from "@/lib/api";

/** Poll-free countdown display: derive remaining seconds from the server's
 *  broadcast end time, corrected by the snapshot's server clock offset. */
const COUNTDOWN_RENDER_TICK_MS = 200;

interface Props {
  code: string;
  token: string;
  isHost: boolean;
  initialRoom: ArenaRoomSnapshot;
  onLeave: () => void;
}

export default function RoomLobby({ code, token, isHost, initialRoom, onLeave }: Props) {
  const [room, setRoom] = useState<ArenaRoomSnapshot>(initialRoom);
  const [closed, setClosed] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Server clock offset (server_now − client now), refreshed per snapshot.
  const clockOffsetRef = useRef(0);
  const [countdownLeft, setCountdownLeft] = useState<number | null>(null);

  useEffect(() => {
    const es = new EventSource(arenaRoomStreamUrl(code));
    const applyRoom = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.room) {
          clockOffsetRef.current = data.room.server_now - Date.now() / 1000;
          setRoom(data.room);
        }
      } catch { /* a malformed frame is dropped; the next tick corrects */ }
    };
    es.addEventListener("snapshot", applyRoom);
    es.addEventListener("player_joined", applyRoom);
    es.addEventListener("countdown", applyRoom);
    es.addEventListener("room_closed", (e: MessageEvent) => {
      let reason = "closed";
      try { reason = JSON.parse(e.data).reason ?? reason; } catch { /* keep default */ }
      setClosed(reason);
      es.close();
    });
    return () => es.close();
  }, [code]);

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
      </div>

      <div className="card flex flex-col gap-2 p-4">
        {room.players.map((p) => (
          <div key={`${p.pet_id}-${p.pet_label}`}
            className="flex items-center justify-between border-b border-white/5 pb-2 last:border-b-0">
            <div className="flex items-center gap-2">
              <span className="text-2xl">🐾</span>
              <span className="font-semibold">{p.pet_label}</span>
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

      {(room.state === "racing" || room.state === "finished") && (
        <div className="card flex flex-col gap-2 p-4">
          <h3 className="font-semibold">🏁 The gun has fired!</h3>
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            Live online racing is the next update — the lobby, the countdown
            and this room all just worked across devices. The race itself
            arrives with R2.
          </p>
        </div>
      )}
    </div>
  );
}
