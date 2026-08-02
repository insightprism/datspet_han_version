"use client";

/**
 * ArenaGame — the Pet Games' page flow (SPEC_PET_ARENA §12 Phases 2-3):
 * setup → [countdown → race] → (hot-seat: handoff → race vs ghost) → results.
 *
 * No backend, no new routes (§15): pets come from the existing house API,
 * stats resolve client-side from the manifest (§5 — every pet ever built
 * competes on day one), and results are computed by the pure referee over the
 * impulse logs. Lane order is CANONICAL across runs — player 1 is lane 0 in
 * both their solo run and the ghost replay — so the referee's numbers are
 * exactly what was on screen (§7.4).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { removePet } from "@/pet";
import { botImpulseLog } from "./bot";
import { CHALLENGES } from "./challenges/registry";
import { ARENA_PET_DISPLAY_SIZE_PX } from "./constants";
import { loadEvent, type ArenaEventDecl } from "./declarations";
import type { ArenaPetInfo, LoadedRacer, RacerConfig, RunAccuracy } from "./gameTypes";
import { jumpEventDurationMs } from "./fieldJump";
import JumpResultsScreen from "./JumpResultsScreen";
import JumpScreen from "./JumpScreen";
import { loadRacer } from "./petLoader";
import type { Impulse } from "./raceEngine";
import { mintRaceSeed } from "./rng";
import RaceScreen from "./RaceScreen";
import ResultsScreen from "./ResultsScreen";
import SetupScreen, { type RaceSetupChoice } from "./SetupScreen";

type Phase =
  | { kind: "setup" }
  | { kind: "loading" }
  | { kind: "race"; run: 0 | 1 }
  | { kind: "handoff" }
  | { kind: "results" };

function buildLaneConfigs(
  choice: RaceSetupChoice, pets: ArenaPetInfo[],
): RacerConfig[] {
  const labelOf = (id: string) => pets.find((p) => p.id === id)?.label ?? "pet";
  if (choice.mode === "bot") {
    const botPet = choice.botPetId!;
    return [
      {
        petId: choice.playerOnePetId, storeId: `${choice.playerOnePetId}#lane0`,
        label: `You — ${labelOf(choice.playerOnePetId)}`,
        kind: "human", handicapName: choice.playerOneHandicap,
      },
      {
        petId: botPet, storeId: `${botPet}#lane1`,
        label: `Bot (${choice.botRung}) — ${labelOf(botPet)}`,
        kind: "bot", handicapName: "none", botRung: choice.botRung,
      },
    ];
  }
  const p2 = choice.playerTwoPetId!;
  return [
    {
      petId: choice.playerOnePetId, storeId: `${choice.playerOnePetId}#lane0`,
      label: `Player 1 — ${labelOf(choice.playerOnePetId)}`,
      kind: "human", handicapName: choice.playerOneHandicap,
    },
    {
      petId: p2, storeId: `${p2}#lane1`,
      label: `Player 2 — ${labelOf(p2)}`,
      kind: "human", handicapName: choice.playerTwoHandicap,
    },
  ];
}

export default function ArenaGame() {
  const [phase, setPhase] = useState<Phase>({ kind: "setup" });
  const [choice, setChoice] = useState<RaceSetupChoice | null>(null);
  const [event, setEvent] = useState<ArenaEventDecl | null>(null);
  const [racers, setRacers] = useState<LoadedRacer[]>([]);
  const [raceSeed, setRaceSeed] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const humanLogsRef = useRef<(Impulse[] | null)[]>([]);
  const accuraciesRef = useRef<(RunAccuracy | null)[]>([]);
  const racersRef = useRef<LoadedRacer[]>([]);
  racersRef.current = racers;

  // The engine reads --pet-display-size for background-size and cell offsets;
  // scope the arena's value to this page the way PetStage does.
  useEffect(() => {
    const prev = document.documentElement.style.getPropertyValue("--pet-display-size");
    document.documentElement.style.setProperty(
      "--pet-display-size", `${ARENA_PET_DISPLAY_SIZE_PX}px`);
    return () => {
      if (prev) document.documentElement.style.setProperty("--pet-display-size", prev);
      else document.documentElement.style.removeProperty("--pet-display-size");
      racersRef.current.forEach((r) => removePet(r.storeId));
    };
  }, []);

  const beginRace = useCallback(async (setup: RaceSetupChoice, pets: ArenaPetInfo[]) => {
    const eventDecl = loadEvent(setup.eventKey);
    if (!eventDecl) return;
    setPhase({ kind: "loading" });
    setLoadError(null);
    try {
      racersRef.current.forEach((r) => removePet(r.storeId));
      const configs = buildLaneConfigs(setup, pets);
      const loaded = await Promise.all(configs.map((c) => loadRacer(c, eventDecl)));
      humanLogsRef.current = configs.map(() => null);
      accuraciesRef.current = configs.map(() => null);
      setChoice(setup);
      setEvent(eventDecl);
      setRacers(loaded);
      setRaceSeed(mintRaceSeed());
      setPhase({ kind: "race", run: 0 });
    } catch {
      setLoadError("Could not fetch a runner's sprite sheet — try again?");
      setPhase({ kind: "setup" });
    }
  }, []);

  const onRunDone = useCallback((run: 0 | 1, humanLaneIndex: number,
                                 log: Impulse[], accuracy: RunAccuracy) => {
    humanLogsRef.current[humanLaneIndex] = log;
    accuraciesRef.current[humanLaneIndex] = accuracy;
    if (choice?.mode === "hotseat" && run === 0) setPhase({ kind: "handoff" });
    else setPhase({ kind: "results" });
  }, [choice]);

  if (phase.kind === "setup") {
    return (
      <>
        {loadError && <div className="card mb-3 p-3" style={{ color: "#f87171" }}>{loadError}</div>}
        <SetupScreen onStart={beginRace} />
      </>
    );
  }

  if (phase.kind === "loading" || !choice || !event) {
    return <div className="card p-4">Walking the athletes to the track…</div>;
  }

  const challenge = CHALLENGES[choice.challengeKey];
  const isJump = event.procedure === "jump";

  if (phase.kind === "race" && choice.mode === "bot") {
    // Field events (§6.6) swap the screen, never the flow: same lanes, same
    // challenge, same seed — a different procedure scores the same log.
    const Screen = isJump ? JumpScreen : RaceScreen;
    return (
      <Screen
        key={`bot-${raceSeed}`}
        event={event} challenge={challenge} difficulty={choice.difficulty}
        raceSeed={raceSeed} lanes={racers} humanLaneIndex={0}
        ghostLogs={racers.map(() => null)}
        runLabel="go!"
        onDone={(log, acc) => onRunDone(0, 0, log, acc)}
      />
    );
  }

  if (phase.kind === "race" && phase.run === 0) {
    const Screen = isJump ? JumpScreen : RaceScreen;
    return (
      <Screen
        key={`p1-${raceSeed}`}
        event={event} challenge={challenge} difficulty={choice.difficulty}
        raceSeed={raceSeed} lanes={[racers[0]]} laneOffset={0}
        humanLaneIndex={0} ghostLogs={[null]}
        runLabel={isJump ? "Player 1 jumps first" : "Player 1 sets the time"}
        onDone={(log, acc) => onRunDone(0, 0, log, acc)}
      />
    );
  }

  if (phase.kind === "handoff") {
    return (
      <div className="card flex flex-col items-center gap-4 p-8 text-center">
        <div className="text-3xl">🔄 Pass the device!</div>
        <p style={{ color: "var(--muted)" }}>
          Player 2, you race player 1's ghost — the very same run, the very same
          questions. Beat it to the line.
        </p>
        <button type="button" className="btn px-8 py-3 text-lg"
          onClick={() => setPhase({ kind: "race", run: 1 })}>
          I'm ready
        </button>
      </div>
    );
  }

  if (phase.kind === "race") {
    if (isJump) {
      // Field events run in sequence, as real ones do — player 2 jumps alone
      // (canonical lane 1, for the jitter stream) chasing player 1's number.
      return (
        <JumpScreen
          key={`p2-${raceSeed}`}
          event={event} challenge={challenge} difficulty={choice.difficulty}
          raceSeed={raceSeed} lanes={[racers[1]]} laneOffset={1}
          humanLaneIndex={0} ghostLogs={[null]}
          runLabel="Player 2 — beat that distance!"
          onDone={(log, acc) => onRunDone(1, 1, log, acc)}
        />
      );
    }
    return (
      <RaceScreen
        key={`p2-${raceSeed}`}
        event={event} challenge={challenge} difficulty={choice.difficulty}
        raceSeed={raceSeed} lanes={racers} laneOffset={0}
        humanLaneIndex={1}
        ghostLogs={[humanLogsRef.current[0], null]}
        runLabel="Player 2 — catch the ghost!"
        onDone={(log, acc) => onRunDone(1, 1, log, acc)}
      />
    );
  }

  // Results: authoritative logs per canonical lane — recorded for humans,
  // regenerated (same seed, same lane, same function) for the bot. A bot's
  // log runs the event's duration: the time limit for a race, the declared
  // attempt schedule for a field event.
  const logs: Impulse[][] = racers.map((racer, lane) => {
    if (racer.kind === "bot") {
      return botImpulseLog(racer.botRung ?? "steady", raceSeed, lane,
        isJump ? jumpEventDurationMs(event) : event.time_limit_s * 1000);
    }
    return humanLogsRef.current[lane] ?? [];
  });

  if (isJump) {
    return (
      <JumpResultsScreen
        event={event} challenge={challenge} difficulty={choice.difficulty}
        raceSeed={raceSeed} lanes={racers} logs={logs}
        accuracies={accuraciesRef.current}
        onRaceAgain={() => {
          humanLogsRef.current = racers.map(() => null);
          setRaceSeed(mintRaceSeed());
          setPhase({ kind: "race", run: 0 });
        }}
        onBackToSetup={() => {
          racersRef.current.forEach((r) => removePet(r.storeId));
          setRacers([]);
          setPhase({ kind: "setup" });
        }}
      />
    );
  }

  return (
    <ResultsScreen
      event={event} challenge={challenge} difficulty={choice.difficulty}
      raceSeed={raceSeed} lanes={racers} logs={logs}
      accuracies={accuraciesRef.current}
      onRaceAgain={() => {
        humanLogsRef.current = racers.map(() => null);
        accuraciesRef.current = racers.map(() => null);
        setRaceSeed(mintRaceSeed());
        setPhase({ kind: "race", run: 0 });
      }}
      onBackToSetup={() => {
        racersRef.current.forEach((r) => removePet(r.storeId));
        setRacers([]);
        setPhase({ kind: "setup" });
      }}
    />
  );
}
