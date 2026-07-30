/**
 * The sign-in return rule (SPEC_DATSPET_FEDERATED_SESSION §4.2, §5.1).
 *
 * Two bugs live in this three-line function, and both have bitten:
 *
 *   - APPENDING a second `return` instead of replacing the prebuilt one. The server
 *     hands us signin_url already carrying `return=/design`; a second parameter is
 *     ambiguous and whichever one wins is a coin flip.
 *   - DROPPING the query. The designer keeps its running build in `?job=<id>`, so a
 *     return path that loses the query loses a 3-minute pet — measured on staging
 *     2026-07-30, pet 332793aaaa66.
 *
 * Pure by construction (session in, string out), which is why it is testable at all
 * in a DOM-free runner.
 */
import { describe, it, expect } from "vitest";
import { signinUrlReturningTo, datsmeRenewUrl, type DatsmeSession } from "@/lib/api";

const SESSION: DatsmeSession = {
  launched: false,
  integrated: true,
  // Exactly the shape the server builds — note it ALREADY has a return.
  signin_url: "https://staging.datsme.me/api/integrations/login-launch?activity=design_a_pet&return=/design",
};

function returnParam(url: string | null): string | null {
  return url ? new URL(url).searchParams.get("return") : null;
}

describe("signinUrlReturningTo", () => {
  it("REPLACES the prebuilt return rather than appending a second one", () => {
    const url = signinUrlReturningTo(SESSION, "/house")!;
    expect(new URL(url).searchParams.getAll("return")).toEqual(["/house"]);
  });

  it("keeps the query string — this is the lost-pet bug", () => {
    expect(returnParam(signinUrlReturningTo(SESSION, "/design/general?job=332793aaaa66")))
      .toBe("/design/general?job=332793aaaa66");
  });

  it("keeps the activity and the host origin the server chose", () => {
    const url = new URL(signinUrlReturningTo(SESSION, "/design/general?job=abc")!);
    expect(url.origin).toBe("https://staging.datsme.me");
    expect(url.searchParams.get("activity")).toBe("design_a_pet");
  });

  it("is null when there is no host to sign in to (standalone)", () => {
    expect(signinUrlReturningTo({ launched: false, integrated: false }, "/house")).toBeNull();
  });
});

describe("datsmeRenewUrl", () => {
  it("marks the return so a declined renewal cannot loop", () => {
    expect(returnParam(datsmeRenewUrl(SESSION, "/house"))).toBe("/house?renewed=1");
  });

  it("uses & when the path already has a query, so both survive", () => {
    // Both halves matter: the job id is the pet, the marker is the loop guard.
    expect(returnParam(datsmeRenewUrl(SESSION, "/design/general?job=abc")))
      .toBe("/design/general?job=abc&renewed=1");
  });
});
