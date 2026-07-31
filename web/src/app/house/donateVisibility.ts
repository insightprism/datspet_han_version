/**
 * Who may be offered the Donate action, and who may be thanked for it
 * (SPEC_PET_STORE §10.1, §10.8).
 *
 * A pure function for the same reason `storeFilter.ts` is one: this is the
 * page's only real decision, it has three inputs that arrive from three
 * different places, and a rule spread across a JSX conditional is a rule
 * nothing can pin. The door re-checks every one of these server-side — this
 * only decides whether a button is worth showing, so getting it wrong shows a
 * button that 403s, never a donation that should not have happened.
 */
import type { DatsmeSession, Entitlement, PetSummary } from "@/lib/api";

/** Is this pet one the donate door would accept from this caller? */
export function canOfferDonate(
  pet: Pick<PetSummary, "donatable">,
  session: DatsmeSession | null,
  entitlement: Entitlement | null,
): boolean {
  // Gate 3, projected per row: only a pet she DESIGNED. A store-adopted pet is
  // stamped `public` and is refused, which is what closes the laundering loop.
  if (!pet.donatable) return false;
  // Gate 1: a DatsMe identity. A donation earns social points, and those need
  // an account to land in.
  if (!session?.launched) return false;
  // Gate 2: the tier lever. Absent means the entitlement has not loaded yet or
  // the field predates this build — treat that as allowed and let the server
  // decide, rather than hiding a working action behind a slow fetch.
  return entitlement?.can_donate !== false;
}

/**
 * Will a donation actually be thanked?
 *
 * Deliberately NOT part of canOfferDonate: freeing a house slot is a legitimate
 * reason to give a pet away, so a missing permission never blocks the action —
 * it only changes what the confirm dialog promises. Undefined means an older
 * backend that does not report it; assume yes and let the host answer, because
 * the failure mode of a wrong `true` is a missing thank-you, while a wrong
 * `false` scares someone out of a donation that would have worked.
 */
export function canBeThanked(session: DatsmeSession | null): boolean {
  return session?.can_be_thanked !== false;
}
