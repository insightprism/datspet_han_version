/**
 * The default first-name pool (owner ask, 2026-08-02) — kid-friendly,
 * single-word pet names. An UNNAMED pet gets one deterministically from its
 * pet id (same identity-decode posture as the athletics nudges, Rev.7): same
 * pet → same default name, forever, on any device, with nothing stored and no
 * migration. Renaming stores the child's choice; clearing falls back to this
 * stable default, never a re-roll.
 *
 * One file to grow — adding names changes NOTHING else, though note that
 * growing the list reshuffles which default an existing unnamed pet lands on
 * (index is hash % length). Pre-launch that costs nothing; post-launch,
 * append thoughtfully.
 */

export const PET_FIRST_NAMES: string[] = [
  // Classics
  "Bella", "Max", "Charlie", "Luna", "Lucy", "Cooper", "Bailey", "Daisy",
  "Sadie", "Molly", "Buddy", "Rocky", "Maggie", "Bear", "Duke", "Tucker",
  "Jack", "Harley", "Sophie", "Zoe", "Toby", "Ginger", "Riley", "Coco",
  "Milo", "Oliver", "Simba", "Leo", "Nala", "Loki", "Ziggy", "Oreo",
  "Pepper", "Penny", "Rosie", "Ruby", "Winston", "Murphy", "Finn", "Ollie",
  "Gus", "Hank", "Bandit", "Rex", "Ace", "Apollo", "Zeus", "Thor",
  "Bruno", "Diesel", "Jax", "Sam", "Sammy", "Jake", "Cody", "Buster",
  "Casey", "Shadow", "Smokey", "Felix", "Whiskers", "Mittens", "Boots",
  "Patches", "Socks", "Tiger", "Tigger", "Tom", "Jerry",
  // Soft + snowy
  "Snowy", "Snowball", "Fluffy", "Muffin", "Cupcake", "Cookie", "Brownie",
  "Fudge", "Caramel", "Toffee", "Peanut", "Pumpkin", "Waffles", "Pickles",
  "Noodle", "Biscuit", "Mochi", "Sushi", "Taco", "Nacho", "Pretzel",
  "Bagel", "Donut", "Churro", "Olive", "Peaches", "Mango", "Kiwi",
  "Berry", "Cherry", "Honey", "Maple", "Cinnamon", "Nutmeg",
  // Garden + weather
  "Basil", "Sage", "Clover", "Ivy", "Fern", "Willow", "Hazel", "Aspen",
  "Cedar", "River", "Brook", "Misty", "Stormy", "Sunny", "Star", "Comet",
  "Nova", "Cosmo", "Astro", "Orbit", "Rocket", "Jet", "Turbo", "Dash",
  "Flash", "Bolt", "Zoom", "Zippy", "Speedy", "Scooter", "Skipper",
  "Hopper", "Pip", "Pippin", "Squeak", "Squirt", "Nibbles", "Nugget",
  "Button", "Bean", "Pinto", "Chip", "Sprout", "Pebbles", "Flint",
  // Gems + metals
  "Onyx", "Jasper", "Opal", "Pearl", "Amber", "Jade", "Topaz", "Crystal",
  "Goldie", "Silver", "Copper", "Rusty", "Sooty", "Ash", "Ember", "Blaze",
  "Spark", "Sparky", "Cinders", "Dusty", "Sandy", "Frosty", "Glacier",
  "Winter", "Summer", "Autumn", "June", "April",
  // Distinguished
  "Oscar", "Henry", "George", "Arthur", "Alfie", "Archie", "Teddy",
  "Freddie", "Frankie", "Ronnie", "Reggie", "Bertie", "Monty", "Percy",
  "Rufus", "Wallace", "Watson", "Sherlock", "Darwin", "Newton", "Tesla",
  "Edison", "Mozart", "Elvis", "Bowie", "Marley", "Nina", "Ella", "Etta",
  "Billie", "Dolly", "Cleo", "Zelda", "Mario", "Luigi",
  // Around the world
  "Koda", "Kona", "Kai", "Miko", "Suki", "Yuki", "Haru", "Momo", "Kenji",
  "Sakura", "Hana", "Bao", "Mei", "Ling", "Tofu", "Miso", "Wasabi",
  "Ramen", "Udon", "Boba", "Chai", "Latte", "Espresso", "Cocoa", "Mocha",
  "Java", "Barley", "Hops",
  // Ranks + roles
  "Scout", "Ranger", "Hunter", "Pilot", "Captain", "Major", "Sarge",
  "Chief", "Bishop", "King", "Queenie", "Prince", "Duchess", "Earl",
  "Lady", "Missy", "Angel", "Lucky", "Happy", "Merry", "Jolly", "Chipper",
  "Giggles", "Smiley", "Bubbles", "Dimples", "Wiggles", "Doodle",
  "Scribble", "Sketch", "Crayon",
  // Makers + music
  "Pixel", "Widget", "Gadget", "Gizmo", "Sprocket", "Ratchet", "Dynamo",
  "Banjo", "Bongo", "Cello", "Piccolo", "Fiddle", "Jazz", "Blues",
  "Tango", "Salsa", "Samba", "Disco", "Boogie", "Melody", "Harmony",
  "Lyric", "Tempo", "Aria", "Sonata",
];

/** 32-bit FNV-1a — a tiny SYNC hash (the athletics decode is async WebCrypto;
 *  a name lookup must not be). Stable across sessions and devices. */
function hashPetId(petId: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < petId.length; i++) {
    h ^= petId.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h;
}

/** The deterministic default first name for a pet id. */
export function defaultPetFirstName(petId: string): string {
  return PET_FIRST_NAMES[hashPetId(petId) % PET_FIRST_NAMES.length];
}
