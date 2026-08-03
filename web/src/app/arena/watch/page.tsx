"use client";

/**
 * /arena/watch — the spectator page (SPEC_PET_ARENA_ROOMS R3). The shareable
 * form is /arena/{code}: nginx serves this shell for that path in prod (the
 * static export cannot host a dynamic segment), and next.config rewrites it
 * in dev. The code is read from the PATH first, ?code= as the fallback, so
 * both URL shapes land here. No account, no token — watching is the §0.5
 * read-only surface, and the link dies with the room.
 */

import { useEffect, useState } from "react";
import SpectatorView from "@/arena/room/SpectatorView";

const ROOM_CODE_IN_PATH = /^\/arena\/([A-Za-z0-9_-]{8,24})$/;

export default function WatchPage() {
  // Read the code client-side: the exported shell is one static file served
  // for every /arena/{code} path, so the server never knows the code.
  const [code, setCode] = useState<string | null>(null);
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    const fromPath = ROOM_CODE_IN_PATH.exec(window.location.pathname)?.[1];
    const fromQuery = new URLSearchParams(window.location.search).get("code");
    setCode(fromPath ?? fromQuery);
    setResolved(true);
  }, []);

  return (
    <div>
      <h1 className="mb-1 text-3xl">📺 Watch a pet race</h1>
      <p className="mb-6 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        A friend sent you a race — here it is, live. Racing your own pets needs
        your own DatsPet; watching needs nothing at all.
      </p>
      {resolved && (code
        ? <SpectatorView code={code} />
        : <div className="card p-4">This link is missing its room code.</div>)}
    </div>
  );
}
