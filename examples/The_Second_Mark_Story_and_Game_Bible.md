# The Second Mark — story and game bible

**Status:** Working foundation, version 0.3. **The Second Mark is the confirmed title.** Vey, the sky Bell, repeated-return corruption, the entity within, and physical combat during Mark silence are established direction. District and faction names, precise balance, and later acts are proposals.

## The game in one breath

A boxed, 2.5D action RPG beginning in the **City of Vey**, in a wider world still to be named. A vast Bell hangs over the entire city and rings whenever anyone dies. The player's first encounter with its power changes how they fight. Repeated returns can temporarily corrupt the Mark and silence magic, while physical combat continues to grow. An individual is trying to exploit the Bell, but an unknown entity inside it is growing on its own.

## The world around Vey: what the player sees

The world extends beyond the city, but Vey is the opening game's centre: a dense city of stacked streets, bridges, markets, old transit passages, and rooftops under one impossible sky. Its neighbourhoods may have different wealth, architecture, and beliefs about resurrection. Nobody remembers the Bell arriving. No building supports it, and no district owns it. You can see it from anywhere the sky opens, always hanging over the city as a whole.

The Bell is enormous and physically unsettling: a dark metal silhouette with a pale inner seam, floating high enough to seem both distant and too large to belong there. Its surface can carry old ridges or scars that become more visible after major story events. **It is silent until a death. Every death within its reach produces a toll**, whether or not that person returns. The tone rolls across Vey; in close scenes, it briefly hushes other sounds. A return may follow, but the toll itself does not guarantee one. The Bell's exact reach beyond the city is a later world-building decision.

The first entrance to Vey uses a classic 2D camera moment: the character walks into a boxed street scene; movement pauses naturally; the camera pans past roofs and stacked scenery to reveal the Bell alone in the sky; then it settles back on the character. A death nearby gives the first toll and changes the sound and reactions in the street. This scene establishes scale without claiming that the Bell sits above one district.

**2.5D presentation target:** The game uses a 2D engine and authored, box-like spaces with visible depth. Characters move through readable walkable planes while layered walls, floors, foreground arches, shadows, and controlled perspective make streets feel almost three-dimensional. Side and top surfaces of buildings can be visible in the same room. The camera pans or frames layers to reveal scale; it does not require a full 3D world or free camera. Combat readability takes priority over illusion of depth.

**Engine context:** This game is planned for the creator's **Expra Engine** in the connected GitHub repository `20204166/expra-engine`. Its README describes 2D transforms and an orthographic Pygame runtime with stable depth/layer ordering and a renderer-neutral design. Build the world plan around 2D layers and camera motion. Check the engine's current implementation before coding features; do not assume perspective meshes or 3D lighting.

## Story the player experiences

The City of Vey lives under the Bell. Nobody knows when it appeared. Whenever someone dies within its reach, it rings; sometimes, that person comes back. The city calls that a blessing. People who return call the new sensation in their hands **the Mark**. They remember the moment that changed them, but nobody agrees on what the Bell wants.

You arrive in Vey as a courier carrying a sealed record of people who returned and then vanished. Before you can deliver it, an alarm sends everyone into an old transit district. A creature has escaped from beneath the city. It might be a bone scavenger, a furnace beast, or a shielded former guard; that encounter can vary from one playthrough to another. What matters is the moment it forces on you.

Perhaps it kills you. The Bell calls you back, and you wake with Death in your blood: your blows can take a little life from a living foe. Perhaps a collapsing structure or a glancing strike spares you by sheer chance, and you wake to Luck: a flicker of possibility that strengthens your next attack or turns a desperate guard into a reprisal. Perhaps you meet the danger head on and block the decisive blow. Your Mark becomes Guard: timing and pressure carried from your shield into your next strike.

The first quest ends in the same place for all three paths. You find the person named on your sealed record. They have returned too many times. Their Mark sometimes goes quiet; for a moment they move with startling physical force, but they are losing pieces of themselves. Before they disappear, they tell you: **“It is learning from us.”**

From there the player travels through districts that reveal what the Mark is doing to the city. The sick are asked to die for a chance at useful power. Fighters are trained to hold a shield against impossible blows. The wealthy stage elaborate accidents to coax Luck into their heirs. Each toll is ordinary enough that people keep living under it, yet the number of disappearances is rising with the city's deaths and returns. None of these groups fully understands the Bell, but each has built a livelihood around it.

At the midpoint, the player finds evidence that the missing returnees' lives have been taken into the Bell. It records the way a person first answers danger and how that response changes after each return. The Mark is useful, but the Bell also siphons the potential that might have grown in that person. **An entity is developing inside the Bell**, unseen from the streets below. A separate individual has begun steering access to returns and Marks for their own purpose, without fully controlling or understanding what is growing there. The player's choices determine whom to trust, whom to rescue, and whether the Bell should keep bringing anyone back at all.

The ending should ask a hard but personal question: if this system gave you the power to survive, can you stop it when it is hurting others? The answer changes the city, the fate of the missing people, and what becomes of the entity. It does **not** erase the player's chosen build.

## First playable chapter: the alarm in the transit district

1. **Arrival and reveal.** The player learns strike, block, movement, and interacting with people. They carry the sealed record, but have no active Mark. The camera pans up from the street to the sky Bell, then returns to the player. The first nearby death makes it ring.
2. **The breach.** Select one of several encounter templates and vary enemy, hazards, and route. Every template exposes a readable lethal danger, a chance event, and a blockable decisive attack. The player has real agency in how they respond.
3. **The first imprint.** Record one of three distinct events: the player's first death and resurrection; a visibly fortunate escape or successful gamble; or a decisive block. Present a short scene reflecting the recorded event and grant Death, Luck, or Guard accordingly.
4. **First practice.** Introduce the affinity's three basic magic combinations through a small fight designed to show how they change strike and block.
5. **The returnee.** Deliver the record, meet the vanishing returnee, hear the warning, and unlock the first skill-tree choice.

**Branch selection rule, proposed:** The first qualifying imprint event wins. Death requires an actual death followed by resurrection. Luck requires an authored, legible lucky escape or gamble, rather than an invisible random roll. Guard requires blocking the encounter's signposted decisive attack; ordinary early blocks do not silently lock the path. If none fires immediately, the encounter continues or offers another readable opportunity. The chosen affinity is permanent for this character. Later deaths can return the player to a checkpoint **through the Bell** and contribute to corruption, without rerolling the first affinity. The random encounter changes the situation, not the availability of all three paths.

### Later deaths and Mark corruption

Every player death gets a Bell toll and a return. Each return leaves **an additional strain on the Mark**, making the Bell's influence visible in the combat loop. Repeated deaths build toward **corruption**; when the threshold is reached, the Mark becomes unavailable temporarily. The character still has Strike, Block, equipment, movement, earned levels, and experience gain. It must be possible to defeat enemies and progress without casting a Mark effect.

During that silent period, physical combat gains a compensating edge: for example, improved damage on well-timed strikes, stronger perfect blocks, or faster recovery after a counter. This is an **earned fallback stance**, not an automatic victory. The player should be able to understand its benefits and survive on skill. The Mark returns after a clear recovery condition, such as winning a set number of meaningful encounters, reaching a sanctuary, or completing a boss phase. **Exact corruption thresholds and recovery conditions are balance decisions**, and ordinary enemies should not be farmable to bypass a major penalty instantly.

The Bell learns from both the use and suppression of Marks. It draws on the unrealised potential of returnees as well as their active power. Mark silence is the early sign that the Bell is taking more than it gives. Disappearances are a later, serious outcome in the world and story, **not a permanent character-deletion punishment for the player**. The player can feel the threat without losing their save or level progress. Increasing city deaths and repeated returns correlate with more disappearances; the precise causal mechanism remains a mystery to uncover.

## The world beyond chapter one

| Group | What they believe | How they enter play |
| --- | --- | --- |
| The Bellkeepers | Resurrection protects Vey and must be regulated. | Offer records, training, and safer routes; conceal what they know about the disappearances. |
| The Ash Wardens | A powerful guard can shelter others from the Bell's worst effects. | Challenge the player in combat and request protection for a vulnerable district. |
| The Chance Houses | Risk can be engineered and sold. | Offer dangerous bargains and information about staged awakenings. |
| The Unreturned | Missing returnees and those trying to rescue them. | Reveal the cost of repeated resurrection and what is inside the Bell. |

These are story factions and possible later progression partners, **not** four extra starting magic classes. Faction quests may grant modifiers, techniques, or conflicting choices without rewriting the character's original Mark.

## Combat foundation

The player always has three base actions:

- **Strike:** a close physical attack. Weapons can change reach, timing, or animation, but the action remains recognisable.
- **Block:** a deliberate defensive action with timing and facing. A well-timed block may count as a perfect block.
- **Mark:** one magic action that prepares or triggers an effect tied to Strike and/or Block. It does not create a separate ranged spell rotation.

All combat paths must remain playable with those three actions. Magic may produce a short-range burst or a fiery shield on contact, but its main payoff is delivered through a physical hit, a guard, a counter, or a close aura. Keep positioning, timing, and enemy tells central.

**Physical progression:** Level gains can improve the universal strike-and-block kit, independent of affinity nodes. Weapons, timing techniques, and passive physical upgrades continue to work during Mark silence. The temporary physical edge during corruption should make this kit satisfying while leaving the restored Mark valuable.

### One Mark, three inputs, up to five combinations

The Mark belongs to one **affinity**: Death, Luck, or Guard. Within that affinity the player learns up to **five named combinations** over a full build. **Three are available early; two unlock later through the affinity tree and story.** A combination is a way to shape the same Mark, not a separate magic school.

**Control proposal:** Press Mark to open a short input window, then enter a sequence using inputs `1`, `2`, and `3`. When the sequence is complete, it resolves into **one** named Mark effect. At the start, the three simple combinations are `1`, `2`, and `3`; later combinations can use sequences such as `1→2` and `2→3`. This keeps the idea of “press one, two, or three, and the inputs become one combination” while leaving the exact input timing open to playtesting. A quick-select option can make learned combinations accessible without typing sequences in high-pressure fights.

Only one Mark effect is primed at a time. A primed effect enhances the next valid strike or block, or briefly alters those actions. New input can replace the primed effect, subject to resource/cooldown rules to be tuned later. The interface should show the queued inputs, the resulting combination's name, and whether it affects Strike, Block, or both.

**Do not treat five as five simultaneous spell buttons.** It is the maximum number of learned recipes within a character's one affinity. A tree changes those recipes and the underlying combat actions.

## The three starting affinities

### Death — “I came back, and something followed”

**Combat identity:** Close-range survival through measured life siphon and risk. It rewards committing to a hit after danger, without turning the player invulnerable.

| Initial input | Working combination | Effect tied to physical combat |
| --- | --- | --- |
| `1` | Siphon Edge | The next strike restores a small share of the **actual damage dealt**, subject to a per-hit cap. |
| `2` | Grave Hold | A successful block stores a little pressure; the next close strike consumes it for a stronger siphon. |
| `3` | Last Breath | While wounded, a successful close strike grants brief damage resistance; a perfect block improves the next strike's healing. |

**Early tree directions:** Siphon (more reliable recovery), Debt (accept a short self-cost for stronger strikes), or Return (bonuses after a near-fatal escape or Bell resurrection, with no incentive to farm deliberate deaths). Suggested late combinations: `1→2` **Blood Reply**, an empowered counter after a block; `2→3` **Borrowed Pulse**, a brief defensive stance whose next strike returns limited health.

**Scaling rule:** Life recovered rises through level and tree investment by adjusting a **bounded percentage of actual physical damage dealt**. The cap, cooldown, enemy eligibility, and healing reductions are tuning values. Never siphon a percentage of a boss's *maximum health*; that would make boss fights collapse as health pools grow.

### Luck — “The world slipped, and I was still standing”

**Combat identity:** Buffs that turn opportunities into stronger attacks and reactive defence. Luck is a manipulable window of advantage, not a build decided by repeated hidden coin flips.

| Initial input | Working combination | Effect tied to physical combat |
| --- | --- | --- |
| `1` | Favoured Strike | The next strike gains a modest damage buff. |
| `2` | Lucky Guard | A successful block returns a close-range spark of damage to the attacker. |
| `3` | Bright Opening | After a successful block or well-timed strike, the next attack gains a brief elemental or light-infused enhancement. |

**Early tree directions:** Fortune (longer, more dependable buff windows), Radiance (light or fire added to strikes and shield contact), or Reversal (greater payoff after blocking while under pressure). Suggested late combinations: `1→2` **Burning Chance**, buff the strike and leave a short-lived fiery guard; `2→3` **Second Opening**, strengthen an attack after a successful retaliation. Any visual fire effect must be explained as a later environmental or tree influence on Luck, rather than a fourth starting affinity.

### Guard — “I held the line, and it held me back”

**Combat identity:** Readable defence, stored force, and offensive parries. A block can empower a future attack, and an attack can briefly protect the player when timed well.

| Initial input | Working combination | Effect tied to physical combat |
| --- | --- | --- |
| `1` | Returning Force | The next successful block stores force that strengthens a subsequent strike. |
| `2` | Braced Edge | A timed strike carries a brief parry window, deflecting some incoming damage during the swing. |
| `3` | Deep Guard | The next block absorbs more pressure; a perfect block grants a stronger close counter. |

**Early tree directions:** Bastion (better protection), Riposte (faster and harder counters), or Tempo (links between attack timing and guard timing). Suggested late combinations: `1→2` **Crossguard**, a strike with a narrow parry window that feeds a counter; `2→3` **Iron Echo**, a stronger block that stores force for the next two strikes. Guard is a magic affinity gained through the decisive first defence; ordinary blocking remains available to everyone.

## Trees and progression rules

Each affinity has its **own small tree**. At the start, it exposes three directional branches and improvements to its three basic combinations. Later quest milestones reveal nodes for the fourth and fifth combinations. A level grants a point on a predictable cadence; story milestones unlock *access* to nodes so exploration matters as well as experience. Exact point budgets and level caps await playtesting.

Nodes should change how Strike and Block interact, not just add percentage damage. Example node types: consume stored block force on a hit; refresh a buff after a perfect block; alter a siphon cap; make an empowered strike carry a brief parry window. Offer respecs for ordinary tree nodes at a reasonable cost; the first affinity stays fixed for the character so the opening has weight. Level scaling improves effectiveness without changing the player's original story event.

Environmental exposures later in the game may **colour** an existing affinity. A furnace region might add heat to Lucky Guard, cauterise a Death wound effect, or turn Guard's stored force into a burning counter. Exposure unlocks optional modifiers within the chosen tree; it does not add a second affinity or a projectile spell school. This is how story locations and faction choices can keep evolving one Mark.

## Rules for future AI collaborators

1. Treat this document as the **current design reference**. If a new mechanic contradicts it, propose the change explicitly rather than silently inventing a replacement.
2. Keep all three first-imprint paths reachable in every first-quest encounter template, with clear player feedback about the decisive event.
3. A character has exactly one starting affinity: Death, Luck, or Guard. Ordinary Strike and Block always remain available.
4. The Mark evolves physical combat. Do not build a conventional ranged spellcaster as the default combat loop.
5. A character can learn at most five named Mark combinations; begin with three. The input sequence resolves to one active effect. Affinity trees modify those combinations.
6. Preserve the Bell above all of Vey, the toll at every death in its reach, the growing entity inside it, and temporary Mark silence after repeated returns. Separate those established premises from proposals about its appearance, factions, combination names, input timings, and numerical balance.
7. When writing quests, show how the affinity changes a scene or a character's response, while preserving the central mystery and shared main plot.
8. Keep procedurally selected opening enemies fair and authored: randomise from tested encounter templates, ensure each offers the same three imprint opportunities, and avoid invisible rules that permanently assign a build.
9. A Mark-silenced character must still level, fight, and finish meaningful encounters with Strike and Block. Show the physical fallback bonus and the condition for restoring the Mark.
10. The person seeking to harness the Bell is distinct from the entity growing inside it. Neither one's identity, motives, or control should be assumed solved before the relevant story reveal.

## Decisions to make together next

- Is combat real-time action, or a slower action game with deliberate cooldowns? That determines how comfortable the `1/2/3` sequence feels.
- Is the first affinity selected through play alone, or should the player also be allowed to choose after the awakening scene for accessibility and build planning?
- How dark should Vey feel: eerie adventure, tragic horror, or something between?
- Does the Bell return every player death while returning only some other people, and what determines its reach beyond Vey?
- What are the exact corruption threshold, duration, and physical fallback bonuses?
- Who is the individual exploiting the Bell, and how much do they understand about the entity inside it?
- Which first affinity should be the reference build for a playable prototype?
