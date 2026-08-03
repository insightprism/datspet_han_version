"use client";

/**
 * LoungeView — inside one lounge (SPEC_PET_ARENA_LOUNGE §3–§5): who's here,
 * the challenge cards, and the racing board. The pet is the identity — every
 * line here names a pet, never a person.
 *
 * Challenges are CANNED (§4.1): the card carries the challenger's own setup
 * picks; there is no text box because there is no field for text to live in.
 * A declined card is a local dismiss — the server never delivers a rejection
 * (§2.3), it just lets the card expire.
 *
 * Accepting (or having your card accepted) hands back an ordinary room seat
 * and this component's job ends — onEnterRoom drops into the same RoomLobby
 * a code-shared race uses. §3.2's pet thumbnails are deferred with the same
 * reasoning as the room lobby's: a paw glyph until an owner asks.
 */

import { useEffect, useRef, useState } from "react";
import {
  acceptLoungeChallenge, arenaWatchUrl, claimLoungeChallenge,
  createLoungeChallenge, leaveArenaLounge,
  type ArenaLoungeChallenge, type ArenaLoungeRoomSeat,
} from "@/lib/api";
import { loadEvent } from "../declarations";
import { useLoungeStream } from "./useLoungeStream";

export interface LoungeSeatHandoff {
  code: string;
  token: string;
  isHost: boolean;
  myLane: number;
  room: ArenaLoungeRoomSeat["room"];
}

interface Props {
  loungeId: string;
  presenceToken: string;
  presenceId: string;
  /** The setup picks a challenge card carries (§4.1). */
  picks: { eventKey: string; challengeKey: string; difficulty: string };
  onEnterRoom: (seat: LoungeSeatHandoff) => void;
  onLeave: () => void;
}

function eventLabel(eventKey: string): string {
  const decl = loadEvent(eventKey);
  return decl ? `${decl.emoji} ${decl.label}` : eventKey.replace(/_/g, " ");
}

function cardText(challenge: ArenaLoungeChallenge): string {
  return `${eventLabel(challenge.event_key)} · ${challenge.challenge_key} · ${
    challenge.difficulty.replace(/_/g, " ")}`;
}

export default function LoungeView({
  loungeId, presenceToken, presenceId, picks, onEnterRoom, onLeave,
}: Props) {
  const { lounge, notFound } = useLoungeStream(loungeId, presenceToken);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // One claim per accepted card, however many snapshots repeat it.
  const claimedRef = useRef<Set<string>>(new Set());

  // §4.2 step 3 — the challenger's half: the moment MY card turns accepted,
  // claim my seat and follow the acceptor into the room.
  useEffect(() => {
    if (!lounge) return;
    const mine = lounge.challenges.find(
      (c) => c.from_presence === presenceId && c.accepted
        && !claimedRef.current.has(c.id));
    if (!mine) return;
    claimedRef.current.add(mine.id);
    claimLoungeChallenge(loungeId, mine.id, presenceToken)
      .then((seat) => onEnterRoom({
        code: seat.code, token: seat.player_token,
        isHost: true, myLane: seat.my_lane, room: seat.room,
      }))
      .catch((e) => setError(
        e instanceof Error ? e.message : "Could not claim the seat"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lounge?.challenges]);

  if (notFound) {
    return (
      <div className="card flex flex-col gap-3 p-4">
        <h2 className="text-xl font-semibold">🚪 This lounge is closed</h2>
        <button type="button" className="btn self-start" onClick={onLeave}>
          ← Back to the arena
        </button>
      </div>
    );
  }
  if (!lounge) {
    return <div className="card p-4">Opening the door…</div>;
  }

  const me = lounge.present.find((p) => p.presence_id === presenceId);
  const fresh = (c: ArenaLoungeChallenge) => c.expires_at > lounge.server_now;
  const incoming = lounge.challenges.filter(
    (c) => c.to_presence === presenceId && !c.accepted
      && !dismissed.has(c.id) && fresh(c));
  const outgoing = lounge.challenges.filter(
    (c) => c.from_presence === presenceId && !c.accepted && fresh(c));
  const labelOf = (pid: string) =>
    lounge.present.find((p) => p.presence_id === pid)?.pet_label ?? "a pet";

  const challengeSomeone = async (toPresence: string) => {
    setError(null);
    try {
      await createLoungeChallenge(loungeId, {
        token: presenceToken, to: toPresence,
        event_key: picks.eventKey, challenge_key: picks.challengeKey,
        difficulty: picks.difficulty,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The challenge did not land");
    }
  };

  const acceptCard = async (challengeId: string) => {
    setError(null);
    try {
      const seat = await acceptLoungeChallenge(
        loungeId, challengeId, presenceToken);
      onEnterRoom({
        code: seat.code, token: seat.player_token,
        isHost: false, myLane: seat.my_lane, room: seat.room,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not accept");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">
          {lounge.emoji} {lounge.label} — the lounge
        </h2>
        <button type="button" className="btn-ghost"
          onClick={() => {
            leaveArenaLounge(loungeId, presenceToken)
              .catch(() => { /* the presence TTL walks us out regardless */ });
            onLeave();
          }}>
          ← Leave
        </button>
      </div>

      {error && (
        <div className="card p-3 text-sm" style={{ color: "#f87171" }}>{error}</div>
      )}

      {/* §4.2 — cards addressed to me, one Accept each; declining is local. */}
      {incoming.map((c) => (
        <div key={c.id} className="card flex flex-wrap items-center gap-3 p-4"
          style={{ borderLeft: "3px solid var(--green)" }}>
          <span className="text-2xl">⚔️</span>
          <div className="flex flex-col">
            <span className="font-semibold">
              {labelOf(c.from_presence)} challenges you!
            </span>
            <span className="text-xs" style={{ color: "var(--muted)" }}>
              {cardText(c)}
            </span>
          </div>
          <div className="ml-auto flex gap-2">
            <button type="button" className="btn"
              onClick={() => acceptCard(c.id)}>
              Race! →
            </button>
            <button type="button" className="btn-ghost"
              onClick={() => setDismissed((d) => new Set(d).add(c.id))}>
              Not now
            </button>
          </div>
        </div>
      ))}
      {outgoing.map((c) => (
        <div key={c.id} className="card p-3 text-sm"
          style={{ color: "var(--muted)" }}>
          ⏳ Waiting for {labelOf(c.to_presence)} to answer your challenge…
        </div>
      ))}

      {/* §3.2 — who's here: pets, never people. */}
      <div className="card flex flex-col gap-2 p-4">
        <h3 className="text-sm font-semibold">In the room</h3>
        {lounge.present.map((p) => (
          <div key={p.presence_id}
            className="flex items-center justify-between border-b border-white/5 pb-2 last:border-b-0">
            <div className="flex items-center gap-2">
              <span className="text-2xl">🐾</span>
              <span className="font-semibold">
                {p.pet_label}{p.presence_id === presenceId ? " (you)" : ""}
              </span>
            </div>
            {p.presence_id !== presenceId && (
              <button type="button" className="btn-ghost"
                disabled={outgoing.some((c) => c.to_presence === p.presence_id)}
                onClick={() => challengeSomeone(p.presence_id)}>
                ⚔️ Challenge
              </button>
            )}
          </div>
        ))}
        {me && lounge.present.length === 1 && (
          <div className="text-sm" style={{ color: "var(--muted)" }}>
            Nobody else is here yet — the first one in picks the music. 🎵
          </div>
        )}
        <div className="pt-1 text-xs" style={{ color: "var(--muted)" }}>
          A challenge races your current picks: {eventLabel(picks.eventKey)} ·{" "}
          {picks.challengeKey} · {picks.difficulty.replace(/_/g, " ")}
        </div>
      </div>

      {/* §5 — the racing board: live lounge contests, watchable by anyone. */}
      {lounge.racing.length > 0 && (
        <div className="card flex flex-col gap-2 p-4">
          <h3 className="text-sm font-semibold">🏁 Racing now</h3>
          {lounge.racing.map((entry) => (
            <div key={entry.room_code}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 pb-2 last:border-b-0">
              <span className="text-sm">
                {entry.pet_labels.join(" vs ")} — {eventLabel(entry.event_key)}
                {entry.state === "finished" ? " (finished)" : ""}
              </span>
              <a className="btn-ghost text-sm" href={arenaWatchUrl(entry.room_code)}
                target="_blank" rel="noreferrer">
                📺 Watch
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
