"use client";

/**
 * RoomLobby — the player's room SESSION (R1+R2): the phase flow
 * lobby → countdown → race → result over the one transport client,
 * useRoomStream (§4.2 — a fix to the stream or the clock lands there,
 * once). This component owns only what a PLAYER sees: the shareable code
 * and watch link, the start button, and the hand-off to the race screen.
 */

import { useState } from "react";
import {
  arenaWatchUrl, startArenaRoom, type ArenaRoomSnapshot,
} from "@/lib/api";
import {
  CLIPBOARD_FEEDBACK_MS, MEDALS,
} from "../constants";
import RoomRaceScreen from "./RoomRaceScreen";
import { useRoomStream } from "./useRoomStream";

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
  const {
    room: streamed, standings, closed, raceClock, countdownLeft, remoteLanes,
  } = useRoomStream(code, { myLane, initialRoom });
  const room = streamed ?? initialRoom;
  const [startError, setStartError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), CLIPBOARD_FEEDBACK_MS);
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
        raceClock={raceClock} remoteLanes={remoteLanes} />
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
