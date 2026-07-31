import { describe, expect, it } from "vitest";
import { canBeThanked, canOfferDonate } from "./donateVisibility";
import type { DatsmeSession, Entitlement, PetSummary } from "@/lib/api";

const designed = { donatable: true } as Pick<PetSummary, "donatable">;
const adopted = { donatable: false } as Pick<PetSummary, "donatable">;
const launched = { launched: true } as DatsmeSession;
const anon = { launched: false } as DatsmeSession;
const allowed = { can_donate: true } as Entitlement;
const barred = { can_donate: false } as Entitlement;

describe("who is offered the Donate action (SPEC_PET_STORE §10.1)", () => {
  it("offers it for a pet she designed, signed in, on an allowing tier", () => {
    expect(canOfferDonate(designed, launched, allowed)).toBe(true);
  });

  it("never offers a pet she did not design — that is the laundering loop", () => {
    // A store-adopted pet is stamped `public`; donating it back to collect a
    // reward is the abuse the ownership check closes, so the button must not
    // even suggest it.
    expect(canOfferDonate(adopted, launched, allowed)).toBe(false);
  });

  it("never offers it to an anonymous browser", () => {
    // A donation earns social points, and those need an account to land in.
    expect(canOfferDonate(designed, anon, allowed)).toBe(false);
    expect(canOfferDonate(designed, null, allowed)).toBe(false);
  });

  it("respects the tier lever the day it is pulled", () => {
    expect(canOfferDonate(designed, launched, barred)).toBe(false);
  });

  it("shows the action while the entitlement is still loading", () => {
    // Failing open here costs at most a button that 403s; failing closed hides
    // a working action behind a fetch that has not returned.
    expect(canOfferDonate(designed, launched, null)).toBe(true);
  });
});

describe("whether a donation will be thanked (§10.8)", () => {
  it("is false when the user has not allowed DatsMe to award points", () => {
    expect(canBeThanked({ launched: true, can_be_thanked: false } as DatsmeSession))
      .toBe(false);
  });

  it("is true once granted", () => {
    expect(canBeThanked({ launched: true, can_be_thanked: true } as DatsmeSession))
      .toBe(true);
  });

  it("assumes yes when an older backend does not report it", () => {
    // A wrong `true` costs a missing thank-you; a wrong `false` scares someone
    // out of a donation that would have worked.
    expect(canBeThanked({ launched: true } as DatsmeSession)).toBe(true);
  });

  it("does NOT gate the action — freeing a slot is a reason on its own", () => {
    const noGrant = { launched: true, can_be_thanked: false } as DatsmeSession;
    expect(canBeThanked(noGrant)).toBe(false);
    expect(canOfferDonate(designed, noGrant, allowed)).toBe(true);
  });
});
