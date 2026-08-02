import ArenaGame from "@/arena/ArenaGame";

/**
 * /arena — the Pet Games (SPEC_PET_ARENA): a track-and-field meet for the
 * pets you built, driven by solved challenges. The page is a thin server
 * shell; the whole game is the client module in web/src/arena/.
 */
export default function ArenaPage() {
  return (
    <div>
      <h1 className="mb-1 text-3xl">🏟️ Pet Games</h1>
      <p className="mb-6 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Your pets, on the track. Answer to move — you are the engine, your pet is
        the exchange rate. Faster answers, faster pet.
      </p>
      <ArenaGame />
    </div>
  );
}
