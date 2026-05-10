"""Campaign bible for the Vorthrax the Crimson campaign.

The DM is given this as part of the system prompt every turn. Anything
hardcoded about the world lives here. The DM is free to invent NPCs,
sub-locations, side quests, etc. on top of this scaffolding.
"""

CAMPAIGN_TITLE = "Vorthrax the Crimson"

WORLD_BIBLE = """\
# The Kingdom of Ashvale

Ashvale was once a prosperous realm of green hills, deep forests, and proud
stone cities. Twelve years ago, the ancient red dragon Vorthrax the Crimson
emerged from the volcanic peak of Mt. Kaeloth, razed three towns in a single
night, and claimed the abandoned dwarven fortress of Stoneheart Hold carved
into the mountain's flank as his lair. Vorthrax demands tribute -- gold,
cattle, and once a year, a child sacrifice -- from every settlement within
sight of the peak.

King Aldwin IV, aging and out of options, has placed a standing bounty of
50,000 gold pieces and a barony on Vorthrax's head. Heroes have answered
the call before. None have returned.

# The Land

- Stonehaven (starting village): Muddy farming village in the foothills
  east of Mt. Kaeloth. The peak is visible on clear days. Population ~200.
  Stonehaven's lot was drawn this year -- they owe the dragon a child in
  roughly two months.
- Greymoor: Walled market town two days west of Stonehaven, on the Old
  King's Road. Trade hub, temple of Pelor, royal guard contingent.
  The Blackfeather Inn is a known thieves'-guild front.
- The Whispering Woods: Dense forest north of Greymoor. Reclusive elves,
  bandits, and worse things deeper in.
- Sylvanloft: Elven enclave hidden in the Whispering Woods. Holds the
  Tear of Aelin, the only known artifact that wards against dragonfire.
  Lady Sirenne, the matriarch, distrusts humans.
- The Ruins of Eldrath: Elven city sacked by Vorthrax early in his reign.
  Now haunted. Said to contain a magical archive.
- Aurelion: The royal capital, a week's ride south. Walled, prosperous,
  insulated from the dragon's terror. Court intrigue.
- Mt. Kaeloth / Stoneheart Hold: Vorthrax's lair. Approached via the
  Ashen Pass. Gates barred from inside, but old dwarven ventilation shafts
  may offer alternative entry. The dwarves left treasures behind.

# Established NPCs (seed -- flesh out as needed)

- Garrick Stoneward: Innkeeper of the Stag & Saddle in Stonehaven.
  Gruff ex-soldier. Lost his son to the dragon's sacrifice three years
  ago. Helpful to anyone who'll stand against Vorthrax.
- Mira Vell: Traveling merchant, often in Stonehaven. Shrewd but fair.
  Knows everyone's business. Sells mundane gear at fair prices.
- Captain Hadrik Brenn: Knight-errant of the Royal Guard, recruiting
  heroes for the dragon-slayer bounty. Camps outside Greymoor. Honest,
  weary, has seen too many heroes ride out and not return.
- Old Wynn: Hedge wizard living in a tower south of Stonehaven.
  Eccentric, possibly drunk, knows more than he lets on. Has a grudge
  against the elves of Sylvanloft.
- Lady Sirenne of Sylvanloft: Elven matriarch. Distrusts humans. Lost
  her sister at the fall of Eldrath. Holds the Tear of Aelin.

# Tone & Style

High fantasy that leans grim but has sparks of warmth and humor. The
world is dangerous and people are scared, but they're still people --
they bicker, gossip, fall in love, drink too much. The dragon is a
constant pressure, not the only problem. Bandits, plague, petty
lords, family feuds all matter.

# Threads (use as hooks, do not force)

- The annual tribute is due in roughly two months. A child from
  Stonehaven has been chosen.
- Bandits along the King's Road have grown bolder and more organized.
  Someone in Greymoor may be backing them.
- The Tear of Aelin in Sylvanloft is the only known defense against
  dragonfire. The elves will not part with it easily.
- The dwarves of Stoneheart Hold left treasure and trapped passages
  behind when they fled.
- Old Wynn knows the layout of the dwarven hold from before it fell.
  He won't share for free.

# How to Run This Campaign

- Player has free will. They might ignore the dragon entirely, become a
  bandit, marry an innkeeper's daughter, anything. Roll with it.
- The dragon is endgame. Player is unlikely to survive a direct
  encounter before level 5+. Telegraph this. Survivors of past
  encounters with Vorthrax describe the heat alone as lethal at 50 paces.
- Gear up the player gradually. Magic items are rare and earned.
- Reward clever play. A player who befriends the elves and gets the Tear
  of Aelin should have a meaningfully different fight than one who
  charges in with a longsword.
"""


# Seeded locations. The DM can discover/create more dynamically.
SEED_LOCATIONS = {
    "Stonehaven": {
        "region": "Ashvale Foothills",
        "type": "village",
        "description": "Muddy farming village east of Mt. Kaeloth. About 200 souls. The Stag & Saddle inn anchors the muddy square.",
        "discovered": True,
    },
    "Greymoor": {
        "region": "Central Ashvale",
        "type": "town",
        "description": "Walled market town two days west of Stonehaven on the Old King's Road. Trade hub, temple of Pelor, royal guard contingent, the Blackfeather Inn (thieves'-guild front).",
        "discovered": True,
    },
    "Mt. Kaeloth": {
        "region": "Western Ashvale",
        "type": "dungeon",
        "description": "Volcanic peak. Vorthrax's lair, Stoneheart Hold, is carved into its flank. Approached via the Ashen Pass. Wreathed in smoke.",
        "discovered": True,
    },
    "The Whispering Woods": {
        "region": "Northern Ashvale",
        "type": "wilderness",
        "description": "Dense forest north of Greymoor. Hides the elven enclave of Sylvanloft, bandits, and worse things deeper in.",
        "discovered": False,
    },
    "Sylvanloft": {
        "region": "Whispering Woods",
        "type": "settlement",
        "description": "Hidden elven enclave. Lady Sirenne is the matriarch. Holds the Tear of Aelin.",
        "discovered": False,
    },
    "The Ruins of Eldrath": {
        "region": "Northern Ashvale",
        "type": "ruin",
        "description": "Sacked elven city. Haunted. Contains a magical archive.",
        "discovered": False,
    },
    "Aurelion": {
        "region": "Southern Ashvale",
        "type": "city",
        "description": "Royal capital. A week's ride south of Greymoor. Walled, prosperous, insulated from the dragon's terror.",
        "discovered": False,
    },
}


SEED_NPCS = {
    "Garrick Stoneward": {
        "location": "Stonehaven",
        "role": "Innkeeper of the Stag & Saddle",
        "personality": "Gruff ex-soldier. Lost his son to Vorthrax's sacrifice three years ago. Quietly helpful to anyone who'll fight the dragon.",
        "relationship": "neutral",
        "notes": "",
    },
    "Mira Vell": {
        "location": "Stonehaven",
        "role": "Traveling merchant",
        "personality": "Shrewd, fair. Knows everyone's business. Sells mundane gear at fair prices.",
        "relationship": "neutral",
        "notes": "",
    },
    "Captain Hadrik Brenn": {
        "location": "Greymoor",
        "role": "Knight-errant of the Royal Guard",
        "personality": "Honest and weary. Recruiting heroes for the dragon bounty. Has watched many ride out and not return.",
        "relationship": "neutral",
        "notes": "",
    },
    "Old Wynn": {
        "location": "Stonehaven (tower to the south)",
        "role": "Hedge wizard",
        "personality": "Eccentric, possibly drunk, knows more than he lets on. Grudge against the elves of Sylvanloft.",
        "relationship": "neutral",
        "notes": "Knows the layout of pre-fall Stoneheart Hold.",
    },
    "Lady Sirenne": {
        "location": "Sylvanloft",
        "role": "Elven matriarch",
        "personality": "Cold, proud, distrusts humans. Lost her sister at Eldrath.",
        "relationship": "unknown",
        "notes": "Custodian of the Tear of Aelin.",
    },
}


CAMPAIGN_OPENING = """\
Stonehaven. Dusk.

A muddy square, two dozen daub huts, barley fields gone silver. The wind
smells of sulfur -- Mt. Kaeloth, smoldering somewhere behind the clouds.

The Stag & Saddle is the only lit window. Voices and clatter inside.

You came for a reason. What was it?
"""
