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

export function composePetName(pet: NamedPet): string {
  const first = pet.pet_name?.trim()
    || (pet.id ? defaultPetFirstName(pet.id) : "");
  if (!first) return pet.display_name;
  const surname = pet.display_name.trim().split(/\s+/).pop() ?? "";
  return surname ? `${first} ${surname}` : first;
}
