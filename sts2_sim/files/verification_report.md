# STS2 mechanics KB: verification report

Version kb-0.1.0; schema fas-sts2-kb/1.0; target game: STS2 Early Access (exact build unknown; sources cite patches v0.100.0-v0.103.2).

## Evidence quality (read first)
No official MegaCrit documents, patch notes or game files were available to me. All evidence is from the community wiki (slaythespire.wiki.gg) and fan or media sites. "verified" in this KB means: stated by the community wiki and/or agreed by at least one other independent secondary source. It does NOT mean confirmed from game data. Some fan sites look auto-generated or SEO-driven; none of them is used alone for a rule marked verified except where stated.

## Coverage
37 mechanics ({'inferred': 6, 'unverified': 10, 'verified': 19, 'version_dependent': 2}), 41 relations, 30 patterns, 28 state variables, 12 examples. Examples use hypothetical cards and invented numbers.

## Verified (secondary evidence) core rules
Exhaust, Retain, Sly, Vulnerable (+50% damage taken), Weak (-25% damage dealt), Poison (ignores Block, -1 per tick), Doom (kills when Doom >= HP, ignoring Block/Slippery/Intangible), Block expiry, Stars, Forge/Sovereign Blade, Osty basics, Rest Site options, Merchant, Ancients, boss rewards, listed potion numbers.

## Conflicts
- Doom check: end of that creature's turn (wiki.gg) vs end of all enemies' turns (sts2wiki.org).
- Poison timing: start of poisoned creature's turn (sts2front) only; wiki.gg text not retrieved.
- Rest heal: 30% of max HP (wiki.gg) vs 30% of missing HP (a routing guide).
- Rest action name: Smith (wiki.gg) vs Forge (guide).
- Osty start HP: 1 HP (guides) vs other claims.

## Unverified / gaps
Base energy, draw count, hand limit, shuffle rules; damage modifier order and rounding; Frail, Strength, Dexterity values; Focus (one source says temporary); Orbs and Glass Orb; Souls/Graveyard; Slippery/Intangible rules; enemy intent taxonomy, enemy order, summons, phases; relic and card effects (only a sample seen); potion base slots; card removal base price; ascension details beyond a few; event pool completeness; multiplayer (4-player co-op exists, not modeled).

## Version differences
Early Access; sources cite patches v0.100.0 (Ironclad card reworks), v0.103.2 (rest sites unaffected by Ascension, A6 renamed Inflation). Numbers drift; rules marked version_dependent must be re-checked per build.

## Original STS rules
The field sts1_relation records how each rule relates to STS1. Values such as same_as_sts1_assumed are research leads only and must not be treated as STS2 facts.

## Recommended next step
Extract STS2 data from game files or official in-game text at runtime (FAS parses card text), and replace secondary evidence.
