/**
 * The name of the pet house, in one place.
 *
 * It drifted the first time it was renamed: the nav said "My Pet House" while
 * the page it opened still said "The pet house", and four other surfaces said
 * something else again. A UI name used in six files is a value, so it gets a
 * named constant like any other.
 *
 * Two registers, and the difference is the speaker:
 *   HOUSE_NAME      — the page's proper name, in the USER's voice. Nav, page
 *                     title, buttons that go there.
 *   HOUSE_NAME_OBJ  — the same house in the SYSTEM's voice, addressing the
 *                     user. "your pet house is full", "saved to your pet house".
 *
 * NOT for DatsMe's house. "your DatsMe house" is a different house on a
 * different site, and copy that means DatsMe must keep saying DatsMe — the
 * possessive makes the two easy to conflate, so never route that wording
 * through here.
 */
export const HOUSE_NAME = "My Pet House";
export const HOUSE_NAME_OBJ = "your pet house";
