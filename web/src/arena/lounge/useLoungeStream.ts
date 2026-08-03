"use client";

/**
 * useLoungeStream — the lounge's one transport client (the useRoomStream
 * discipline, SPEC_PET_ARENA_LOUNGE §3.3): one EventSource, one handler.
 * Deliberately simpler than the room's hook — every lounge event carries the
 * FULL lounge snapshot, so there are no deltas, no clock, and no adapters;
 * a reconnect is made whole by the snapshot-first frame alone.
 */

import { useEffect, useState } from "react";
import {
  arenaLoungeStreamUrl, heartbeatArenaLounge,
  type ArenaLoungeSnapshot,
} from "@/lib/api";
import { LOUNGE_HEARTBEAT_MS } from "../constants";

/** Every lounge event name the server broadcasts — one list, one handler. */
const LOUNGE_EVENTS = [
  "snapshot", "presence_changed", "challenge_created", "challenge_accepted",
] as const;

export interface LoungeStreamState {
  lounge: ArenaLoungeSnapshot | null;
  /** True when the lounge id answers nothing at all. */
  notFound: boolean;
}

export function useLoungeStream(
  loungeId: string, presenceToken: string,
): LoungeStreamState {
  const [lounge, setLounge] = useState<ArenaLoungeSnapshot | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    const es = new EventSource(arenaLoungeStreamUrl(loungeId));
    const apply = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.lounge) setLounge(data.lounge);
      } catch { /* a malformed frame is dropped; the next event corrects */ }
    };
    LOUNGE_EVENTS.forEach((name) => es.addEventListener(name, apply));
    es.addEventListener("lounge_closed", () => {
      setNotFound(true);
      es.close();
    });
    return () => es.close();
  }, [loungeId]);

  // §3.1 — presence is a heartbeat, not a session: stop beating (tab closed,
  // network gone) and the sweeper walks you out after the TTL.
  useEffect(() => {
    const iv = setInterval(() => {
      heartbeatArenaLounge(loungeId, presenceToken)
        .catch(() => { /* the next beat retries; the TTL is the truth */ });
    }, LOUNGE_HEARTBEAT_MS);
    return () => clearInterval(iv);
  }, [loungeId, presenceToken]);

  return { lounge, notFound };
}
