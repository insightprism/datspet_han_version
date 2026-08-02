"use client";

/**
 * SetupScreen — pick the event, the runner, the opponent, the challenge, the
 * handicap. The §6.3.3 presentation rules live here:
 *   1. Locked events are SHOWN greyed with their requirement, never hidden —
 *      a gate a child does not understand is just a wall.
 *   2. Every unsatisfied clause is named, alternatives and all ("needs Jump
 *      or Play").
 *   3. The racewalk guarantees no pet is ever empty-handed.
 * Stat bars are visible (§16.6): the design→performance link is the feature,
 * and a hidden stat is indistinguishable from a random one.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { listPets, petManifestUrl } from "@/lib/api";
import { composePetName } from "@/lib/petName";
import PetThumbnail from "@/components/PetThumbnail";
import {
  deriveIdentityNudges, qualifies, resolveAthletics, unsatisfiedClauses,
  type AthleticsManifest,
} from "./athletics";
import { CHALLENGES, listChallenges } from "./challenges/registry";
import {
  ARENA_EVENTS, BOT_RUNGS, HANDICAP_LADDER, type ArenaEventDecl,
} from "./declarations";
import PetProfileModal from "./PetProfileModal";
import { PoseBadges, PoseLegend } from "./PoseBadges";
import StatBars from "./StatBars";
import type { ArenaPetInfo } from "./gameTypes";

export interface RaceSetupChoice {
  eventKey: string;
  challengeKey: string;
  difficulty: string;
  mode: "bot" | "hotseat";
  botRung: string;
  playerOnePetId: string;
  playerOneHandicap: string;
  playerTwoPetId: string | null;
  playerTwoHandicap: string;
  botPetId: string | null;
}

interface Props {
  onStart: (choice: RaceSetupChoice, pets: ArenaPetInfo[]) => void;
}

function clauseText(clause: string[]): string {
  return clause.map((p) => p[0].toUpperCase() + p.slice(1)).join(" or ");
}

function requiresText(requires: string[][]): string {
  return requires.map(clauseText).join(" and ");
}


export default function SetupScreen({ onStart }: Props) {
  const [pets, setPets] = useState<ArenaPetInfo[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [eventKey, setEventKey] = useState("racewalk");
  const [challengeKey, setChallengeKey] = useState("arithmetic");
  const [difficulty, setDifficulty] = useState(CHALLENGES.arithmetic.ladder[0].key);
  const [mode, setMode] = useState<"bot" | "hotseat">("bot");
  const [botRung, setBotRung] = useState("steady");
  const [playerOnePetId, setPlayerOnePetId] = useState<string | null>(null);
  const [playerTwoPetId, setPlayerTwoPetId] = useState<string | null>(null);
  const [botPetId, setBotPetId] = useState<string | null>(null);
  const [playerOneHandicap, setPlayerOneHandicap] = useState("none");
  const [playerTwoHandicap, setPlayerTwoHandicap] = useState("none");
  // The animated profile (owner ask): clicking your already-selected athlete
  // opens it — the card is a <button>, so a nested trigger is not an option.
  // Stored by ID and derived from the list, so a rename inside the modal
  // updates the open profile and the card behind it in one state change.
  const [profilePetId, setProfilePetId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const summaries = await listPets();
        const loaded = await Promise.all(summaries.map(async (s) => {
          const r = await fetch(petManifestUrl(s.id));
          if (!r.ok) return null;
          const manifest: AthleticsManifest = await r.json();
          const info: ArenaPetInfo = {
            id: s.id,
            // "Joe Leopard" — the child's name for the pet, if they gave one.
            label: composePetName(s),
            display_name: s.display_name,
            pet_name: s.pet_name,
            manifest,
            poses: Object.keys(manifest.animations ?? {}),
            // The real numbers, id-nudges included (§3.4 Rev.7) — the bars a
            // child compares are exactly what the race will use.
            previewStats: resolveAthletics(
              manifest, await deriveIdentityNudges(s.id)),
          };
          return info;
        }));
        if (!cancelled) setPets(loaded.filter((p): p is ArenaPetInfo => p !== null));
      } catch {
        if (!cancelled) setLoadError("Could not load your pets — is the backend up?");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const profilePet = pets?.find((p) => p.id === profilePetId) ?? null;

  const applyRename = useCallback((petId: string, petName: string | null) => {
    setPets((cur) => cur === null ? cur : cur.map((p) => p.id === petId
      ? {
          ...p,
          pet_name: petName,
          label: composePetName({ pet_name: petName, display_name: p.display_name }),
        }
      : p));
  }, []);

  const event: ArenaEventDecl = useMemo(
    () => ARENA_EVENTS.find((e) => e.key === eventKey) ?? ARENA_EVENTS[0],
    [eventKey]);
  const challenge = CHALLENGES[challengeKey];
  const qualified = useMemo(
    () => (pets ?? []).filter((p) => qualifies(p.poses, event.requires)),
    [pets, event]);

  // Keep picks coherent as the event changes: an unqualified pick is cleared,
  // never silently carried into a race it cannot enter.
  useEffect(() => {
    const stillIn = (id: string | null) =>
      id !== null && qualified.some((p) => p.id === id) ? id : null;
    setPlayerOnePetId((id) => stillIn(id) ?? qualified[0]?.id ?? null);
    setPlayerTwoPetId((id) => stillIn(id));
    setBotPetId((id) => stillIn(id));
  }, [qualified]);

  const effectiveBotPetId = botPetId
    ?? qualified.find((p) => p.id !== playerOnePetId)?.id
    ?? playerOnePetId;

  const startable = playerOnePetId !== null
    && (mode === "bot" ? effectiveBotPetId !== null : playerTwoPetId !== null);

  if (loadError) return <div className="card p-4">{loadError}</div>;
  if (pets === null) return <div className="card p-4">Loading your pets…</div>;
  if (pets.length === 0) {
    return (
      <div className="card p-4">
        The meet needs athletes! <Link href="/design" className="underline">Design a pet</Link>{" "}
        and come back.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* 1 — the event. Locked ones shown, never hidden (§6.3.3). */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">1 · Pick the event</h3>
        <div className="flex flex-wrap gap-2">
          {ARENA_EVENTS.map((e) => {
            const count = (pets ?? []).filter((p) => qualifies(p.poses, e.requires)).length;
            const locked = count === 0;
            return (
              <button key={e.key} type="button"
                onClick={() => setEventKey(e.key)}
                disabled={locked}
                className="card p-3 text-left"
                style={{
                  minWidth: 150,
                  opacity: locked ? 0.45 : 1,
                  outline: eventKey === e.key ? "2px solid var(--green)" : "none",
                }}>
                <div className="text-lg">{e.emoji} <b>{e.label}</b></div>
                <div className="text-xs" style={{ color: "var(--muted)" }}>
                  {e.distance_m} m · needs {requiresText(e.requires)}
                </div>
                <div className="text-xs" style={{ color: locked ? "#f87171" : "var(--green)" }}>
                  {locked
                    ? `no pet qualifies yet — poses unlock events`
                    : `${count} of your ${pets.length} pets qualify`}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* 2 — the challenge (§8.1: any challenge drives any event). */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">2 · Pick the challenge</h3>
        <div className="flex flex-wrap items-center gap-2">
          {listChallenges().map((c) => (
            <button key={c.key} type="button" className="btn-ghost"
              style={challengeKey === c.key ? { outline: "2px solid var(--green)" } : undefined}
              onClick={() => {
                setChallengeKey(c.key);
                setDifficulty(c.ladder[0].key);
              }}>
              {c.emoji} {c.label}
            </button>
          ))}
          {challenge.ladder.length > 1 && (
            <select className="input text-sm"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}>
              {challenge.ladder.map((rung) => (
                <option key={rung.key} value={rung.key}>{rung.label}</option>
              ))}
            </select>
          )}
        </div>
      </section>

      {/* 3 — the athlete. Unqualified pets greyed with the reason named. */}
      <section>
        <h3 className="mb-1 text-sm font-semibold">3 · Pick your athlete</h3>
        <div className="mb-1 text-[11px]" style={{ color: "var(--muted)" }}>
          Click your athlete again to watch them move.
        </div>
        <PoseLegend />
        <div className="flex flex-wrap gap-2">
          {pets.map((p) => {
            const ok = qualifies(p.poses, event.requires);
            const missing = unsatisfiedClauses(p.poses, event.requires);
            return (
              <button key={p.id} type="button" disabled={!ok}
                onClick={() => {
                  // First click selects; a click on the already-selected
                  // athlete opens the animated profile (owner ask) — the
                  // card is itself a button, so no nested ▶ trigger.
                  if (playerOnePetId === p.id) setProfilePetId(p.id);
                  else setPlayerOnePetId(p.id);
                }}
                className="card p-2 text-left"
                style={{
                  width: 150,
                  opacity: ok ? 1 : 0.45,
                  outline: playerOnePetId === p.id ? "2px solid var(--green)" : "none",
                }}>
                <div className="flex items-center gap-2">
                  <PetThumbnail petId={p.id} size={40} />
                  <span className="text-sm font-semibold">{p.label}</span>
                </div>
                {ok
                  ? <StatBars stats={p.previewStats} />
                  : <div className="mt-1 text-[11px]" style={{ color: "#f87171" }}>
                      needs {missing.map(clauseText).join(" and ")}
                    </div>}
                <PoseBadges poses={p.poses} />
              </button>
            );
          })}
        </div>
      </section>

      {/* 4 — the race type: solo vs the bot, or two players hot-seat. */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">4 · Pick your race type</h3>
        <div className="mb-2 flex gap-2">
          <button type="button" className="btn-ghost"
            style={mode === "bot" ? { outline: "2px solid var(--green)" } : undefined}
            onClick={() => setMode("bot")}>🤖 Race the bot</button>
          <button type="button" className="btn-ghost"
            style={mode === "hotseat" ? { outline: "2px solid var(--green)" } : undefined}
            onClick={() => setMode("hotseat")}>👧👦 Two players, one device</button>
        </div>
        {mode === "bot" ? (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span style={{ color: "var(--muted)" }}>Bot pace:</span>
            {Object.entries(BOT_RUNGS).map(([rung, rate]) => (
              <button key={rung} type="button" className="btn-ghost capitalize"
                style={botRung === rung ? { outline: "2px solid var(--green)" } : undefined}
                onClick={() => setBotRung(rung)}>
                {rung} ({rate}/s)
              </button>
            ))}
            <span style={{ color: "var(--muted)" }}>Bot's pet:</span>
            <select className="input"
              value={effectiveBotPetId ?? ""}
              onChange={(e) => setBotPetId(e.target.value)}>
              {qualified.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}{p.id === playerOnePetId ? " (twin of yours)" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span style={{ color: "var(--muted)" }}>Player 2's pet:</span>
            <select className="input"
              value={playerTwoPetId ?? ""}
              onChange={(e) => setPlayerTwoPetId(e.target.value || null)}>
              <option value="">— pick —</option>
              {qualified.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
            <span className="text-xs" style={{ color: "var(--muted)" }}>
              Player 1 races first, then player 2 races their ghost — same questions for both.
            </span>
          </div>
        )}
      </section>

      {/* 5 — handicaps: explicit and visible, never secretly easier sums (§8.3.1). */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">5 · Head start? (everyone can see it)</h3>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span style={{ color: "var(--muted)" }}>
            {mode === "hotseat" ? "Player 1:" : "You:"}
          </span>
          <select className="input"
            value={playerOneHandicap}
            onChange={(e) => setPlayerOneHandicap(e.target.value)}>
            {Object.entries(HANDICAP_LADDER).map(([name, mult]) => (
              <option key={name} value={name}>{name.replace(/_/g, " ")} ×{mult}</option>
            ))}
          </select>
          {mode === "hotseat" && (
            <>
              <span style={{ color: "var(--muted)" }}>Player 2:</span>
              <select className="input"
                value={playerTwoHandicap}
                onChange={(e) => setPlayerTwoHandicap(e.target.value)}>
                {Object.entries(HANDICAP_LADDER).map(([name, mult]) => (
                  <option key={name} value={name}>{name.replace(/_/g, " ")} ×{mult}</option>
                ))}
              </select>
            </>
          )}
        </div>
      </section>

      <PetProfileModal pet={profilePet} onClose={() => setProfilePetId(null)}
        onRenamed={applyRename} />

      <button type="button" className="btn self-start px-8 py-3 text-lg"
        disabled={!startable}
        onClick={() => {
          if (!startable || playerOnePetId === null) return;
          onStart({
            eventKey, challengeKey, difficulty, mode, botRung,
            playerOnePetId, playerOneHandicap,
            playerTwoPetId: mode === "hotseat" ? playerTwoPetId : null,
            playerTwoHandicap,
            botPetId: mode === "bot" ? effectiveBotPetId : null,
          }, pets);
        }}>
        🏟️ To the starting line
      </button>
    </div>
  );
}
