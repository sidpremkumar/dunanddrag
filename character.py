"""Character data + interactive character creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import dice
import ui


# --- Race / class data ----------------------------------------------------

RACES = {
    "Human": {
        "bonuses": {"STR": 1, "DEX": 1, "CON": 1, "INT": 1, "WIS": 1, "CHA": 1},
        "blurb": "Versatile and ambitious. +1 to every stat.",
    },
    "Elf": {
        "bonuses": {"DEX": 2, "INT": 1},
        "blurb": "Graceful, long-lived, keen-sighted. +2 DEX, +1 INT.",
    },
    "Dwarf": {
        "bonuses": {"CON": 2, "STR": 1},
        "blurb": "Stout, stubborn, mountain-born. +2 CON, +1 STR.",
    },
    "Halfling": {
        "bonuses": {"DEX": 2, "CHA": 1},
        "blurb": "Small, lucky, quick-fingered. +2 DEX, +1 CHA.",
    },
}


CLASSES = {
    "Fighter": {
        "hit_die": 10,
        "primary": "STR",
        "blurb": "Soldier, mercenary, knight. Heavy armor and blade.",
        "armor": ("Chainmail", 16, 0),  # base AC, dex cap (0 = none)
        "shield": True,
        "starting_inventory": [
            ("Longsword", "1d8 slashing, versatile (1d10 two-handed).", 1, "weapon", {"damage": "1d8", "type": "martial"}),
            ("Chainmail", "Heavy armor. AC 16, no DEX bonus, disadvantage on Stealth.", 1, "armor", {"ac": 16, "dex_cap": 0}),
            ("Wooden shield", "+2 AC.", 1, "shield", {"ac_bonus": 2}),
            ("Adventurer's pack", "Bedroll, tinderbox, rations (5 days), waterskin, rope.", 1, "misc", {}),
        ],
    },
    "Rogue": {
        "hit_die": 8,
        "primary": "DEX",
        "blurb": "Scoundrel, thief, scout. Strikes from shadow.",
        "armor": ("Leather armor", 11, 99),
        "shield": False,
        "starting_inventory": [
            ("Shortsword", "1d6 piercing, finesse.", 1, "weapon", {"damage": "1d6", "type": "finesse"}),
            ("Shortbow", "1d6 piercing, range 80/320.", 1, "weapon", {"damage": "1d6", "type": "ranged"}),
            ("Leather armor", "Light armor. AC 11 + DEX.", 1, "armor", {"ac": 11, "dex_cap": 99}),
            ("Thieves' tools", "For locks and traps. +proficiency on relevant checks.", 1, "tool", {}),
            ("Adventurer's pack", "Bedroll, tinderbox, rations (5 days), waterskin, rope.", 1, "misc", {}),
        ],
    },
    "Wizard": {
        "hit_die": 6,
        "primary": "INT",
        "blurb": "Scholar of the arcane. Frail but versatile.",
        "armor": ("Robes", 10, 99),
        "shield": False,
        "starting_inventory": [
            ("Quarterstaff", "1d6 bludgeoning, versatile.", 1, "weapon", {"damage": "1d6", "type": "simple"}),
            ("Spellbook", "Contains your prepared spells. Cantrips: Fire Bolt, Mage Hand, Light. Level 1: Magic Missile, Shield, Detect Magic. (3 spell slots / day.)", 1, "focus", {}),
            ("Robes", "Cloth. AC 10 + DEX.", 1, "armor", {"ac": 10, "dex_cap": 99}),
            ("Component pouch", "Spell components.", 1, "misc", {}),
            ("Scholar's pack", "Bedroll, ink, parchment, tinderbox, rations.", 1, "misc", {}),
        ],
    },
    "Cleric": {
        "hit_die": 8,
        "primary": "WIS",
        "blurb": "Channeler of divine power. Heals and smites.",
        "armor": ("Scale mail", 14, 2),
        "shield": True,
        "starting_inventory": [
            ("Mace", "1d6 bludgeoning.", 1, "weapon", {"damage": "1d6", "type": "simple"}),
            ("Scale mail", "Medium armor. AC 14 + DEX (max 2).", 1, "armor", {"ac": 14, "dex_cap": 2}),
            ("Wooden shield", "+2 AC.", 1, "shield", {"ac_bonus": 2}),
            ("Holy symbol", "Focus for divine spells. Cantrips: Sacred Flame, Light, Guidance. Level 1: Cure Wounds, Bless, Healing Word. (3 spell slots / day.)", 1, "focus", {}),
            ("Priest's pack", "Bedroll, alms box, vestments, rations.", 1, "misc", {}),
        ],
    },
    "Ranger": {
        "hit_die": 10,
        "primary": "DEX",
        "blurb": "Wilderness warrior. Bow, blade, and tracker's eye.",
        "armor": ("Leather armor", 11, 99),
        "shield": False,
        "starting_inventory": [
            ("Longbow", "1d8 piercing, range 150/600.", 1, "weapon", {"damage": "1d8", "type": "ranged"}),
            ("Shortsword", "1d6 piercing, finesse.", 1, "weapon", {"damage": "1d6", "type": "finesse"}),
            ("Leather armor", "Light armor. AC 11 + DEX.", 1, "armor", {"ac": 11, "dex_cap": 99}),
            ("Quiver (20 arrows)", "Arrows for the longbow.", 1, "ammo", {"count": 20}),
            ("Explorer's pack", "Bedroll, tinderbox, rations (5 days), waterskin, rope, hunter's traps.", 1, "misc", {}),
        ],
    },
}


# Standard 5e XP table truncated to level 10.
XP_TABLE = [0, 0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000]


def level_for_xp(xp: int) -> int:
    for lv in range(len(XP_TABLE) - 1, 0, -1):
        if xp >= XP_TABLE[lv]:
            return lv
    return 1


def xp_to_next(xp: int) -> int:
    lv = level_for_xp(xp)
    if lv >= len(XP_TABLE) - 1:
        return 0
    return XP_TABLE[lv + 1] - xp


@dataclass
class Character:
    name: str
    race: str
    char_class: str
    background: str  # free text — fed to DM
    level: int = 1
    xp: int = 0
    hp: int = 10
    max_hp: int = 10
    ac: int = 10
    gold: int = 25
    stats: dict = field(default_factory=lambda: {
        "STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10,
    })
    inventory: list = field(default_factory=list)
    equipped: dict = field(default_factory=dict)  # slot -> item name
    conditions: list = field(default_factory=list)  # e.g. "poisoned", "blessed"

    def stat_mod(self, stat: str) -> int:
        return (self.stats[stat] - 10) // 2

    def proficiency(self) -> int:
        return 2 + (self.level - 1) // 4

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "race": self.race,
            "char_class": self.char_class,
            "background": self.background,
            "level": self.level,
            "xp": self.xp,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "ac": self.ac,
            "gold": self.gold,
            "stats": dict(self.stats),
            "inventory": list(self.inventory),
            "equipped": dict(self.equipped),
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Character":
        return cls(
            name=d["name"],
            race=d["race"],
            char_class=d["char_class"],
            background=d["background"],
            level=d.get("level", 1),
            xp=d.get("xp", 0),
            hp=d.get("hp", 10),
            max_hp=d.get("max_hp", 10),
            ac=d.get("ac", 10),
            gold=d.get("gold", 25),
            stats=dict(d.get("stats", {})),
            inventory=list(d.get("inventory", [])),
            equipped=dict(d.get("equipped", {})),
            conditions=list(d.get("conditions", [])),
        )


# --- Creation flow --------------------------------------------------------


def _ask_choice(prompt: str, options: dict[str, dict], detail_key: str = "blurb") -> str:
    keys = list(options.keys())
    while True:
        print()
        for i, k in enumerate(keys, 1):
            print(f"  {i}. {k} -- {options[k][detail_key]}")
        raw = ui.prompt(prompt).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        for k in keys:
            if k.lower() == raw.lower():
                return k
        ui.warn("Pick one by number or name.")


def _roll_stats() -> list[int]:
    return sorted([dice.roll_4d6_drop_lowest() for _ in range(6)], reverse=True)


def _assign_stats(rolls: list[int]) -> dict:
    stats = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}
    remaining = list(rolls)
    order = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    print()
    ui.system("Assign each rolled value to a stat.")
    for s in order:
        while True:
            print(f"  Remaining: {remaining}")
            raw = ui.prompt(f"  Value for {s}: ").strip()
            if not raw.isdigit():
                ui.warn("Enter a number from the remaining pool.")
                continue
            v = int(raw)
            if v not in remaining:
                ui.warn("That value isn't in the remaining pool.")
                continue
            stats[s] = v
            remaining.remove(v)
            break
    return stats


def create_character() -> Character:
    ui.banner("Character Creation", "Roll a hero to face Vorthrax")

    # Name
    while True:
        name = ui.prompt("Name your hero: ").strip()
        if name:
            break
        ui.warn("Give them a name.")

    # Race
    ui.section("Race")
    race = _ask_choice("Pick a race (number or name): ", RACES)

    # Class
    ui.section("Class")
    char_class = _ask_choice("Pick a class (number or name): ", CLASSES)

    # Stats
    ui.section("Ability Scores")
    ui.system("Rolling 4d6 drop lowest, six times. You may reroll the set once.")
    rolls = _roll_stats()
    print(f"  Rolls: {rolls}  (sum {sum(rolls)})")
    if ui.prompt("Reroll? [y/N] ").strip().lower() == "y":
        rolls = _roll_stats()
        print(f"  New rolls: {rolls}  (sum {sum(rolls)})")
    stats = _assign_stats(rolls)
    for stat, bonus in RACES[race]["bonuses"].items():
        stats[stat] += bonus
    ui.system(f"After racial bonuses: {stats}")

    # Background
    ui.section("Background")
    ui.system("Tell the DM who this character is. A sentence or two on backstory,\n"
              "personality, why they came to Stonehaven. The DM will use this.")
    background = ui.prompt("Background: ").strip()
    if not background:
        background = f"A {race.lower()} {char_class.lower()} drawn to Ashvale by the dragon-slayer bounty."

    # Build character
    cls = CLASSES[char_class]
    con_mod = (stats["CON"] - 10) // 2
    max_hp = cls["hit_die"] + con_mod
    armor_name, armor_ac, dex_cap = cls["armor"]
    dex_mod = (stats["DEX"] - 10) // 2
    ac = armor_ac + min(dex_mod, dex_cap)
    if cls["shield"]:
        ac += 2

    char = Character(
        name=name,
        race=race,
        char_class=char_class,
        background=background,
        level=1,
        xp=0,
        max_hp=max_hp,
        hp=max_hp,
        ac=ac,
        gold=25,
        stats=stats,
        inventory=[
            {"name": n, "description": d, "quantity": q, "type": t, "properties": p}
            for (n, d, q, t, p) in cls["starting_inventory"]
        ],
        equipped={},
    )

    # Auto-equip armor + main weapon
    for it in char.inventory:
        if it["type"] == "armor":
            char.equipped["armor"] = it["name"]
        elif it["type"] == "shield":
            char.equipped["offhand"] = it["name"]
        elif it["type"] == "weapon" and "mainhand" not in char.equipped:
            char.equipped["mainhand"] = it["name"]

    ui.section("Summary")
    print_sheet(char)
    return char


def print_sheet(char: Character) -> None:
    print()
    print(f"  {char.name} -- {char.race} {char.char_class}, level {char.level}")
    print(f"  HP {char.hp}/{char.max_hp}   AC {char.ac}   XP {char.xp} (next: {xp_to_next(char.xp)})   Gold {char.gold}")
    mods = "  ".join(f"{s} {char.stats[s]:>2} ({char.stat_mod(s):+d})" for s in ["STR","DEX","CON","INT","WIS","CHA"])
    print(f"  {mods}")
    print(f"  Proficiency +{char.proficiency()}")
    if char.conditions:
        print(f"  Conditions: {', '.join(char.conditions)}")
    print(f"  Background: {char.background}")
    if char.equipped:
        eq = ", ".join(f"{slot}: {name}" for slot, name in char.equipped.items())
        print(f"  Equipped: {eq}")
    if char.inventory:
        print("  Inventory:")
        for it in char.inventory:
            qty = f" x{it['quantity']}" if it.get("quantity", 1) > 1 else ""
            print(f"    - {it['name']}{qty} -- {it['description']}")
