// Public surface of the pet engine for Pet Maker's pages. The engine files
// are copied verbatim from datsme_me/web/src/pet (see that repo's
// docs/SPEC_PET_RUNTIME_ADOPTION.md); only this index and the host component
// (components/PetStage.tsx, replacing datsme's PetOverlay) differ.
export { PetCanvas } from "./PetCanvas";
export { ensurePet, removePet, getPet, setAnim, petStore } from "./petStore";
// Frame primitives for the arena's race driver (SPEC_PET_ARENA §7.6/§9.2):
// the arena is a second DRIVER over the same primitives — it mounts these
// instead of useAutoStateMachine and paces pets from the impulse stream.
// This index is one of the two files the runtime designates as legitimately
// host-specific, so widening it is the sanctioned seam rather than a fork.
export {
  setBgPos, applyTransform, getDisplayFrame, resolveRestAnim,
  recomputeMirroringPolicy,
} from "./petStore";
export type { PetState } from "./petStore";
export { animsFromManifest, deriveRows } from "./manifest";
export type { RawManifest } from "./manifest";
export { useAnimationLoop } from "./useAnimationLoop";
export { useAutoStateMachine } from "./behaviors/useAutoStateMachine";
export { useCursorFollow } from "./behaviors/useCursorFollow";
export type { CursorFollowMode } from "./behaviors/useCursorFollow";
export { useClickToWalk } from "./behaviors/useClickToWalk";
export { useClickPetExcited } from "./behaviors/useClickPetExcited";
export { useDomZones } from "./behaviors/useDomZones";
export { DEFAULT_PERSONALITY } from "./personality";
export type { PetPersonality } from "./personality";
export type { PetSheet, MirroringPolicy } from "./types";
