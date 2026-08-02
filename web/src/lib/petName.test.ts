/** composePetName — "«first name» «animal»", the owner's naming design. */
import { describe, expect, it } from "vitest";
import { defaultPetFirstName, PET_FIRST_NAMES } from "./petFirstNames";
import { composePetName } from "./petName";

describe("composePetName", () => {
  it("composes first name + the animal surname", () => {
    expect(composePetName({ pet_name: "Joe", display_name: "White Snow Leopard" }))
      .toBe("Joe Leopard");
    expect(composePetName({ pet_name: "Tobby", display_name: "Chinese Boy" }))
      .toBe("Tobby Boy");
    expect(composePetName({ pet_name: "Lisa", display_name: "Purple Dragon" }))
      .toBe("Lisa Dragon");
  });

  it("an unnamed pet keeps its breed display name", () => {
    expect(composePetName({ pet_name: null, display_name: "White Snow Leopard" }))
      .toBe("White Snow Leopard");
    expect(composePetName({ display_name: "Black Bat" })).toBe("Black Bat");
    expect(composePetName({ pet_name: "   ", display_name: "Black Bat" }))
      .toBe("Black Bat");
  });

  it("a single-word breed still gets a surname", () => {
    expect(composePetName({ pet_name: "Milo", display_name: "Hedgehog" }))
      .toBe("Milo Hedgehog");
  });

  it("the surname is the ANIMAL, skipping trailing colors and fillers", () => {
    // The owner's rule: the last name identifies the animal — even when the
    // breed name ends in a color ("Golden A Phoenix Red").
    expect(composePetName({ pet_name: "Jazz", display_name: "Golden A Phoenix Red" }))
      .toBe("Jazz Phoenix");
    expect(composePetName({ pet_name: "Kiwi", display_name: "Blue Emerald A Baby Dragon" }))
      .toBe("Kiwi Dragon");
    // An all-color name falls back to its literal last word.
    expect(composePetName({ pet_name: "Sunny", display_name: "Golden Red" }))
      .toBe("Sunny Red");
  });
});

describe("the id-derived default name (owner ask)", () => {
  it("an unnamed pet WITH an id gets a stable default first name", () => {
    const a = composePetName({ id: "pet00000001", pet_name: null,
                               display_name: "White Snow Leopard" });
    const b = composePetName({ id: "pet00000001", pet_name: null,
                               display_name: "White Snow Leopard" });
    expect(a).toBe(b);                       // same pet, same name, forever
    const first = a.split(" ")[0];
    expect(PET_FIRST_NAMES).toContain(first);
    expect(a.endsWith(" Leopard")).toBe(true);
  });

  it("a stored name always beats the default", () => {
    expect(composePetName({ id: "pet00000001", pet_name: "Joe",
                            display_name: "White Snow Leopard" }))
      .toBe("Joe Leopard");
  });

  it("different ids spread across the pool", () => {
    const names = new Set(
      Array.from({ length: 50 }, (_, i) => defaultPetFirstName(`pet${i}`)));
    expect(names.size).toBeGreaterThan(20);  // a hash, not a constant
  });

  it("the name pool is clean: unique, non-empty, single-word", () => {
    expect(new Set(PET_FIRST_NAMES).size).toBe(PET_FIRST_NAMES.length);
    for (const name of PET_FIRST_NAMES) {
      expect(name.trim()).toBe(name);
      expect(name.length).toBeGreaterThan(1);
      expect(name.includes(" ")).toBe(false);
    }
  });
});
