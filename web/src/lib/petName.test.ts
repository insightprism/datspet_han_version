/** composePetName — "«first name» «animal»", the owner's naming design. */
import { describe, expect, it } from "vitest";
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
});
