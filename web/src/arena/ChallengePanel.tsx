"use client";

/**
 * ChallengePanel — the ONE challenge input surface (F5's de-fork): prompt,
 * tap / choice / typed inputs, the hurdle-gate banner and amber, and the
 * lockout affordances. Mounted by the solo RaceScreen and the room
 * RoomRaceScreen alike; the screens own what a submission MEANS
 * (challenges/answerRules.ts) and where a correct answer goes — this owns
 * only what the child sees and touches.
 */

import { type RefObject } from "react";
import {
  HURDLE_JUMP_ACCENT, HURDLE_JUMP_ACCENT_BG,
} from "./constants";
import type { ArenaChallenge, ChallengeQuestion } from "./challenges/registry";

interface Props {
  challenge: ArenaChallenge;
  question: ChallengeQuestion;
  atGate: boolean;
  lockedOut: boolean;
  given: string;
  onGivenChange: (value: string) => void;
  onSubmit: (given: string) => void;
  inputRef?: RefObject<HTMLInputElement>;
}

export default function ChallengePanel({
  challenge, question, atGate, lockedOut, given, onGivenChange, onSubmit,
  inputRef,
}: Props) {
  return (
    <div className="card p-4 text-center"
      style={atGate
        ? { borderColor: HURDLE_JUMP_ACCENT, background: HURDLE_JUMP_ACCENT_BG }
        : undefined}>
      {/* Rev.9 — the jump moment announces itself: color + banner. */}
      {atGate && (
        <div className="mb-2 text-sm font-bold"
          style={{ color: HURDLE_JUMP_ACCENT }}>
          🚧 JUMP! {challenge.ladder.length > 1
            ? "A harder one clears the hurdle:" : "Clear the hurdle!"}
        </div>
      )}
      {challenge.inputKind === "tap" ? (
        <button
          type="button"
          className="btn w-full py-8 text-3xl"
          style={atGate
            ? { background: HURDLE_JUMP_ACCENT_BG, color: HURDLE_JUMP_ACCENT,
                borderColor: HURDLE_JUMP_ACCENT }
            : undefined}
          onPointerDown={() => onSubmit("")}
        >
          {atGate ? "TAP to JUMP!" : question.prompt}
        </button>
      ) : challenge.inputKind === "choice" && question.choices ? (
        <div className="flex flex-col items-center gap-3">
          <div className="text-4xl font-bold">{question.prompt} = ?</div>
          <div className="flex flex-wrap justify-center gap-3">
            {question.choices.map((choice) => (
              <button key={choice} type="button"
                className="btn min-w-24 px-8 py-4 text-2xl"
                disabled={lockedOut}
                style={atGate
                  ? { background: HURDLE_JUMP_ACCENT_BG, color: HURDLE_JUMP_ACCENT,
                      borderColor: HURDLE_JUMP_ACCENT }
                  : undefined}
                onClick={() => onSubmit(choice)}>
                {choice}
              </button>
            ))}
          </div>
          {lockedOut && (
            <div className="text-sm" style={{ color: "#f87171" }}>
              Not quite — here&apos;s a fresh one…
            </div>
          )}
        </div>
      ) : (
        <form
          onSubmit={(e) => { e.preventDefault(); onSubmit(given); }}
          className="flex flex-col items-center gap-3"
        >
          <div className="text-4xl font-bold">
            {challenge.inputKind === "numeric"
              ? `${question.prompt} = ?`
              : question.prompt}
          </div>
          <div className="flex gap-2">
            <input
              ref={inputRef}
              autoFocus
              inputMode={challenge.inputKind === "numeric" ? "numeric" : "text"}
              value={given}
              disabled={lockedOut}
              onChange={(e) => onGivenChange(e.target.value)}
              className={`${challenge.inputKind === "numeric" ? "w-32" : "w-64"} rounded-lg border bg-transparent px-3 py-2 text-center text-2xl`}
              style={lockedOut ? { borderColor: "#f87171" } : undefined}
            />
            <button type="submit" className="btn" disabled={lockedOut}>Go</button>
          </div>
          {lockedOut && (
            <div className="text-sm" style={{ color: "#f87171" }}>
              Not quite — take a breath…
            </div>
          )}
        </form>
      )}
    </div>
  );
}
