"""Static ASCII art used by the game (title screen, class sigils, etc.).

The DM can also generate dynamic art at runtime via the `show_art` tool;
that's rendered through ui.art_block().
"""

# Title screen: stylized dragon silhouette + campaign banner.
# Lines kept under 80 columns so it fits a normal terminal.

TITLE_ART = r"""
                                    /\
                              ___    ||
                             /   \   ||
                       ____ /  o  \__||___/\
                      /                \   \
                     | _   __    __   _ \   \_
                     || \  \/    \/  / \\    _|
                     | \_\__/____\__/_/  >--' /
                      \________________/____ /
                              ||  ||
                             _||__||_
                            (___||___)
"""

CAMPAIGN_BANNER = r"""
   ╔════════════════════════════════════════════════════════════════════╗
   ║                                                                    ║
   ║       V  O  R  T  H  R  A  X     T  H  E     C  R  I  M  S  O  N  ║
   ║                                                                    ║
   ║              ◈  A solo D&D-style CLI campaign  ◈                   ║
   ║                  with an LLM as Dungeon Master                     ║
   ║                                                                    ║
   ╚════════════════════════════════════════════════════════════════════╝
"""


# Small sigils shown next to each class during character creation.
# Each is a 5-line block, rendered side-by-side with the class menu.

CLASS_SIGILS: dict[str, str] = {
    "Fighter": (
        "    ▲    \n"
        "    █    \n"
        "  ──█──  \n"
        "    █    \n"
        "    ╨    "
    ),
    "Rogue": (
        "    ▲    \n"
        "   ╱█╲   \n"
        "    █    \n"
        "    █    \n"
        "    ╨    "
    ),
    "Wizard": (
        "    ✦    \n"
        "    │    \n"
        "    │    \n"
        "    │    \n"
        "   ─┴─   "
    ),
    "Cleric": (
        "    ✚    \n"
        "   ╱█╲   \n"
        "    █    \n"
        "    █    \n"
        "    ╨    "
    ),
    "Ranger": (
        "  ╲┃     \n"
        "   ╲┃    \n"
        "    ╲┃─→ \n"
        "   ╱┃    \n"
        "  ╱┃     "
    ),
}


# Race emblems (compact, one line each).
RACE_EMBLEMS: dict[str, str] = {
    "Human":    "[ ◈ ] Versatile, ambitious",
    "Elf":      "[ ✧ ] Graceful, long-lived",
    "Dwarf":    "[ ⛰ ] Stout, mountain-born",
    "Halfling": "[ ☘ ] Small, quick-fingered",
}


# A small rendering of Mt. Kaeloth used as a flourish on the title screen.
KAELOTH_SIL = r"""
                       /\
                      /  \      ~smoke~
                     /    \    .
                    /  /\  \  ' .
                  _/  /  \  \_  '.
                _/   /    \   \_
              _/   _/      \_   \_
            _/   _/          \_   \_
           /   _/   Kaeloth    \_   \
          /___/                  \___\
"""


# Death screen — when the player's HP is 0 and they fail a death save.
DEATH_ART = r"""
              ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
              ▒                 ▒
              ▒    HERE LIES    ▒
              ▒                 ▒
              ▒  {name:^15}  ▒
              ▒                 ▒
              ▒    Lv {level:^2}        ▒
              ▒                 ▒
              ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
"""
