"use client";

/**
 * SpectatorView — SPEC_PET_ARENA_ROOMS R3: the watchable race. Anyone holding
 * the room URL sees the lobby fill, the countdown, every lane live, and the
 * referee's standings — and can do nothing else (§0.5: read-only; the stream
 * is the same one players get, minus the ability to send). The transport is
 * useRoomStream with myLane: null — every lane is remote here.
 *
 * Pets load through the room-scoped asset routes (§4.3): the code is the
 * capability, no account exists, and the links die with the room (§6 — a
 * shared link stops working, which is the correct default).
 *
 * §14.4 (should spectators see the questions?) is an OPEN owner call — until
 * it is made, the race and the result are shown, the questions are not.
 */

import { useEffect, useMemo, useState } from "react";
import { roomPetAssetUrls } from "@/lib/api";
import { removePet } from "@/pet";
import ArenaTrack, { type TrackLane } from "../ArenaTrack";
import {
  MEDALS, SPECTATOR_RENDER_TICK_MS,
} from "../constants";
import { loadEvent } from "../declarations";
import type { LoadedRacer } from "../gameTypes";
import { loadRacer } from "../petLoader";
import { RemoteLane, useRoomStream } from "./useRoomStream";

export default function SpectatorView({ code }: { code: string }) {
  const {
    room, standings, closed, notFound, raceClock, countdownLeft, remoteLanes,
  } = useRoomStream(code, { myLane: null });
  const [racers, setRacers] = useState<(LoadedRacer | null)[] | null>(null);

  const event = useMemo(
    () => room ? loadEvent(room.event_key) : null,
    [room?.event_key]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Load every entered pet through the room-scoped routes once players exist.
  const playerKey = room?.players.map((p) => p.pet_id).join(",") ?? "";
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
        assets: roomPetAssetUrls(code, p.pet_id),
      }, event).catch(() => null)));
      if (!cancelled) setRacers(loaded);
    })();
    return () => {
      cancelled = true;
      room.players.forEach((p, i) => removePet(`${p.pet_id}#watch${i}`));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerKey, event, code]);

  // Re-render on a slow cadence while racing so the clock advances — ticks
  // feed lane adapters (refs), so nothing else re-renders the header.
  const [, setRenderTick] = useState(0);
  useEffect(() => {
    if (room?.state !== "racing") return;
    const iv = setInterval(
      () => setRenderTick((t) => t + 1), SPECTATOR_RENDER_TICK_MS);
    return () => clearInterval(iv);
  }, [room?.state]);

  const trackLanes: TrackLane[] = useMemo(() => {
    if (!racers) return [];
    return racers.flatMap((racer, i) => racer === null ? [] : [{
      storeId: racer.storeId,
      label: racer.label,
      handicapName: racer.handicapName,
      racingPose: racer.racingPose,
      hopPose: ["jump", "play"].find((p) => racer.stats.poses.includes(p)),
      // The hook pre-registers an adapter per roster lane (F6); the belt
      // registers any miss INTO the map so it still receives ticks.
      integrator: remoteLanes.get(i) ?? (() => {
        const lane = new RemoteLane();
        remoteLanes.set(i, lane);
        return lane;
      })(),
      log: [],
    }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
