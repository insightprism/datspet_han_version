/** F7 — the seat survives a reload, and a corrupt seat self-clears. */
import { describe, expect, it } from "vitest";
import {
  clearRoomSeat, loadRoomSeat, ROOM_SESSION_KEY, saveRoomSeat,
} from "./roomSession";

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
    key: () => null,
    get length() { return m.size; },
  } as Storage;
}

describe("roomSession", () => {
  it("round-trips a seat", () => {
    const s = memoryStorage();
    saveRoomSeat(s, { code: "abc", token: "t", isHost: true, myLane: 0 });
    expect(loadRoomSeat(s)).toEqual(
      { code: "abc", token: "t", isHost: true, myLane: 0 });
    clearRoomSeat(s);
    expect(loadRoomSeat(s)).toBeNull();
  });

  it("a corrupt or partial seat clears itself", () => {
    const s = memoryStorage();
    s.setItem(ROOM_SESSION_KEY, "{not json");
    expect(loadRoomSeat(s)).toBeNull();
    expect(s.getItem(ROOM_SESSION_KEY)).toBeNull();
    s.setItem(ROOM_SESSION_KEY, JSON.stringify({ code: "abc" }));
    expect(loadRoomSeat(s)).toBeNull();
  });
});
