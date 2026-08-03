/**
 * roomSession — F7 / SPEC_PET_ARENA_ROOMS §14.3: "a mid-race reload will
 * happen constantly on children's devices; they can rejoin with the same
 * token." The player's seat lives here (sessionStorage: per-tab, gone when
 * the tab goes) so ArenaGame can rehydrate the room phase on mount instead
 * of dropping a reloaded child to the setup screen while their lane sits
 * frozen. Pure over an injected Storage, so the rules are testable without
 * a browser.
 */

export const ROOM_SESSION_KEY = "datspet.arena.room.v1";

export interface RoomSeat {
  code: string;
  token: string;
  isHost: boolean;
  myLane: number;
}

export function saveRoomSeat(storage: Storage, seat: RoomSeat): void {
  storage.setItem(ROOM_SESSION_KEY, JSON.stringify(seat));
}

export function loadRoomSeat(storage: Storage): RoomSeat | null {
  const raw = storage.getItem(ROOM_SESSION_KEY);
  if (!raw) return null;
  try {
    const seat = JSON.parse(raw);
    if (typeof seat?.code === "string" && typeof seat?.token === "string"
        && typeof seat?.isHost === "boolean"
        && typeof seat?.myLane === "number") {
      return seat as RoomSeat;
    }
  } catch { /* a corrupt seat is no seat */ }
  clearRoomSeat(storage);
  return null;
}

export function clearRoomSeat(storage: Storage): void {
  storage.removeItem(ROOM_SESSION_KEY);
}
