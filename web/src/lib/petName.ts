/**
 * Pet name composition (owner design, 2026-08-02): the child's chosen first
 * name + the animal as a surname — "Joe Leopard", "Tobby Boy", "Lisa Dragon".
 * An unnamed pet keeps its breed display name.
 *
 * The surname is the display name's LAST WORD, which is the animal in every
 * breed name this factory writes ("White Snow Leopard" → "Leopard"). Composed
 * at read time, everywhere a pet is shown — the stored `pet_name` is only the
 * first name, and nothing in the bundle or the DPP surface is rewritten by a
 * rename.
 */

import { defaultPetFirstName } from "./petFirstNames";

export interface NamedPet {
  /** The pet's unique id — the DEFAULT first name derives from it (stable,
   *  never stored). Without an id, an unnamed pet shows its breed name. */
  id?: string;
  pet_name?: string | null;
  display_name: string;
}

/** Words that describe a breed but are never the ANIMAL — colors and fillers.
 *  The surname rule (owner design: the last name identifies the animal) scans
 *  from the end PAST these, so "Golden A Phoenix Red" surnames as "Phoenix",
 *  not "Red". If every word is on this list (a breed named only in colors),
 *  the literal last word is the honest fallback. */
const NON_ANIMAL_WORDS = new Set([
  "a", "baby", "little", "big",
  "red", "blue", "green", "golden", "gold", "silver", "white", "black",
  "brown", "yellow", "purple", "pink", "orange", "grey", "gray", "emerald",
  "ruby", "sapphire", "crimson", "scarlet", "azure", "violet", "teal",
]);

/** The animal word a pet is surnamed with. */
export function animalSurname(displayName: string): string {
  const words = displayName.trim().split(/\s+/).filter(Boolean);
  for (let i = words.length - 1; i >= 0; i--) {
    if (!NON_ANIMAL_WORDS.has(words[i].toLowerCase())) return words[i];
  }
  return words[words.length - 1] ?? "";
}

export function composePetName(pet: NamedPet): string {
  const first = pet.pet_name?.trim()
    || (pet.id ? defaultPetFirstName(pet.id) : "");
  if (!first) return pet.display_name;
  const surname = animalSurname(pet.display_name);
  return surname ? `${first} ${surname}` : first;
}
