"""DM tools. The DM mutates game state only by calling these.

Each tool: a Bedrock Converse `toolSpec` schema + an executor that takes
the GameState and the tool input and returns a string result. The result
string is fed back to the DM as a tool result so it can narrate.
"""

from __future__ import annotations

from typing import Any, Callable

import dice
import ui
from character import XP_TABLE, level_for_xp, xp_to_next, CLASSES
from state import GameState


# --- Schemas -------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "toolSpec": {
            "name": "roll_dice",
            "description": (
                "Roll dice for any uncertain outcome: skill checks, saving throws, "
                "attack rolls, damage, perception, etc. ALWAYS use this for randomness "
                "instead of inventing results. For ability checks pass the player's "
                "ability modifier (and proficiency bonus, if proficient) as `modifier`."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "dice_notation": {
                        "type": "string",
                        "description": "Dice in standard notation, e.g. '1d20', '2d6', '1d8+3'.",
                    },
                    "modifier": {
                        "type": "integer",
                        "description": "Total modifier to add to the roll (ability mod + proficiency, etc.). Default 0.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "What this roll is for. E.g. 'Stealth check, hiding behind crates' or 'Longsword attack vs goblin'.",
                    },
                    "dc": {
                        "type": "integer",
                        "description": "Optional difficulty class. If provided, the result will indicate success/failure vs this DC.",
                    },
                },
                "required": ["dice_notation", "reason"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "change_hp",
            "description": (
                "Change the player's HP. Negative for damage, positive for healing. "
                "Always call this when the player takes damage or is healed -- "
                "do not just narrate it."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "Negative = damage, positive = healing."},
                    "reason": {"type": "string", "description": "Why HP changed, e.g. 'Bandit hit for 6 slashing'."},
                },
                "required": ["amount", "reason"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "award_xp",
            "description": "Award XP to the player. Auto-checks for level up and reports the result back to you. Award after defeating foes, completing quests, or major roleplay moments.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "XP awarded (positive)."},
                    "reason": {"type": "string"},
                },
                "required": ["amount", "reason"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "change_gold",
            "description": "Change the player's gold. Negative to spend/lose, positive to gain.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["amount", "reason"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "add_item",
            "description": "Add an item to the player's inventory. Use for loot, purchases, gifts. If the item already exists with the same name, quantity stacks.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string", "description": "Short description of what the item is and does."},
                    "quantity": {"type": "integer", "description": "Default 1."},
                    "item_type": {"type": "string", "description": "One of: weapon, armor, shield, focus, tool, consumable, ammo, treasure, misc."},
                    "properties": {
                        "type": "object",
                        "description": "Optional structured properties, e.g. {'damage': '1d8', 'type': 'martial'} for weapons.",
                        "additionalProperties": True,
                    },
                },
                "required": ["name", "description", "item_type"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "remove_item",
            "description": "Remove an item (or N copies) from the player's inventory.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "integer", "description": "Default 1. If quantity >= held, the item is fully removed."},
                    "reason": {"type": "string"},
                },
                "required": ["name", "reason"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "equip_item",
            "description": "Equip an item the player owns into a slot (mainhand, offhand, armor, accessory). Unequips anything already in that slot.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "slot": {"type": "string", "description": "mainhand | offhand | armor | accessory"},
                },
                "required": ["name", "slot"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "set_location",
            "description": (
                "Set the player's current location. If the location does not yet exist on "
                "the world map, it will be created and marked discovered. Use this whenever "
                "the player moves between distinct named places (a village, a dungeon room, "
                "a clearing). Don't use for every step inside one location."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string", "description": "Description of the location -- only required if creating it."},
                    "region": {"type": "string", "description": "Region name -- only required if creating it."},
                    "location_type": {"type": "string", "description": "village | town | city | wilderness | dungeon | ruin | settlement | landmark | other"},
                },
                "required": ["name"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "note_npc",
            "description": (
                "Create or update an NPC dossier. Call this whenever the player meets a "
                "new NPC, or when a notable interaction shifts an existing NPC's "
                "relationship with the player. The dossier is shown back to you on every "
                "future turn so use it as your memory of who's who."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "location": {"type": "string", "description": "Where they're usually found."},
                    "role": {"type": "string", "description": "What they do, e.g. 'blacksmith', 'thief lord'."},
                    "personality": {"type": "string", "description": "Voice and disposition. Lock this in once you've voiced them."},
                    "relationship": {"type": "string", "description": "ally | friendly | neutral | wary | hostile | enemy | unknown"},
                    "notes": {"type": "string", "description": "Anything important about past interactions, secrets, what they owe / are owed, etc. Append to existing notes."},
                },
                "required": ["name"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "set_quest",
            "description": "Create, update, or close out a quest in the player's quest log.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "description": "active | completed | failed | abandoned"},
                    "reward": {"type": "string", "description": "Optional reward summary."},
                },
                "required": ["name", "status"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "set_combat",
            "description": "Mark whether the player is currently in combat, and a brief summary of the situation (enemies, terrain, initiative). Set in_combat=false when the encounter ends.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "in_combat": {"type": "boolean"},
                    "summary": {"type": "string", "description": "Short situation summary, or empty when ending combat."},
                },
                "required": ["in_combat"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "journal",
            "description": (
                "Write a short journal entry summarizing a meaningful event from this scene. "
                "These entries are your long-term memory across many turns. Keep them concise "
                "(1-2 sentences). Write one when: the player completes a meaningful action, "
                "meets a key NPC, learns a secret, gains a major item, or a scene ends. "
                "Don't journal every trivial action."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "entry": {"type": "string"},
                },
                "required": ["entry"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "rest",
            "description": "Apply a rest. 'short' restores some HP (1d8 + CON, once). 'long' restores HP to full and clears non-permanent conditions. Only call when the player chooses to rest in a safe enough place.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "rest_type": {"type": "string", "description": "short | long"},
                    "narration_hint": {"type": "string", "description": "Optional context, e.g. 'camped in the woods'."},
                },
                "required": ["rest_type"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "set_condition",
            "description": "Add or remove a condition on the player (e.g. poisoned, blessed, frightened, exhausted).",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string"},
                    "active": {"type": "boolean", "description": "true to add, false to remove."},
                    "reason": {"type": "string"},
                },
                "required": ["condition", "active"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "show_art",
            "description": (
                "Render a multi-line ASCII art picture in a framed panel for the player. "
                "Use it OFTEN -- roughly one piece every 2-4 turns whenever there is "
                "something concrete to draw: a new location (silhouette, gate, room layout), "
                "an NPC's face or sigil, a creature in combat, a weapon or magic item, a "
                "map, a mood beat (campfire, rain, ruin). Skip only when nothing visual "
                "changed. Hand-drawn printable ASCII / box-drawing chars, max ~70 cols x "
                "~12 rows. Aim for RECOGNIZABLE shapes (a tree, a sword, a face), not "
                "abstract scribbles. No color codes; the renderer adds color."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "art": {"type": "string", "description": "Multi-line ASCII art. Use \\n between rows."},
                    "caption": {"type": "string", "description": "Optional short caption shown beneath the art."},
                    "subject": {"type": "string", "description": "Brief tag of what is depicted (location/npc/item name). Used for logging."},
                },
                "required": ["art"],
            }},
        }
    },
]


# --- Executors -----------------------------------------------------------


def _find_item(state: GameState, name: str) -> dict | None:
    name_l = name.lower()
    for it in state.player.inventory:
        if it["name"].lower() == name_l:
            return it
    return None


def _exec_roll_dice(state: GameState, args: dict) -> str:
    notation = args["dice_notation"]
    modifier = int(args.get("modifier") or 0)
    reason = args.get("reason", "")
    dc = args.get("dc")
    try:
        result = dice.roll(notation, extra_modifier=modifier)
    except ValueError as e:
        return f"ERROR: {e}"

    label = reason or notation
    ui.roll(label, result["total"], result["detail"], dc=dc)

    msg = f"Rolled {notation}{(f' +{modifier}' if modifier > 0 else f' {modifier}' if modifier < 0 else '')}: {result['detail']} = {result['total']}"
    if dc is not None:
        msg += f". DC {dc}: {'SUCCESS' if result['total'] >= dc else 'FAIL'}."
    if notation.lower().endswith("d20") or notation.lower() == "d20":
        if result["rolls"][0] == 20:
            msg += " (NATURAL 20!)"
        elif result["rolls"][0] == 1:
            msg += " (NATURAL 1!)"
    return msg


def _exec_change_hp(state: GameState, args: dict) -> str:
    amount = int(args["amount"])
    reason = args.get("reason", "")
    p = state.player
    before = p.hp
    p.hp = max(0, min(p.max_hp, p.hp + amount))
    delta = p.hp - before
    if amount < 0:
        ui.event("DAMAGE", f"-{-amount} HP ({reason}). HP: {p.hp}/{p.max_hp}")
    elif amount > 0:
        ui.event("HEAL", f"+{amount} HP ({reason}). HP: {p.hp}/{p.max_hp}")
    if p.hp == 0:
        ui.event("DOWN", f"{p.name} has fallen unconscious.")
        return f"HP changed by {delta} ({reason}). Player is now at 0 HP and unconscious."
    return f"HP changed by {delta} ({reason}). Player HP is now {p.hp}/{p.max_hp}."


def _exec_award_xp(state: GameState, args: dict) -> str:
    amount = int(args["amount"])
    reason = args.get("reason", "")
    p = state.player
    old_level = p.level
    p.xp += amount
    new_level = level_for_xp(p.xp)
    ui.event("XP", f"+{amount} XP ({reason}). Total: {p.xp}.")

    leveled_msg = ""
    while new_level > p.level:
        p.level += 1
        cls = CLASSES[p.char_class]
        gained_hp = (cls["hit_die"] // 2 + 1) + p.stat_mod("CON")
        gained_hp = max(1, gained_hp)
        p.max_hp += gained_hp
        p.hp = p.max_hp  # full heal on level up
        ui.event("LEVEL UP", f"{p.name} reaches level {p.level}! +{gained_hp} max HP. Healed to full.")
        leveled_msg += f" Leveled up to {p.level} (+{gained_hp} max HP, healed to full)."

    return (f"Awarded {amount} XP ({reason}). XP: {p.xp} (next level: {xp_to_next(p.xp)})."
            + leveled_msg)


def _exec_change_gold(state: GameState, args: dict) -> str:
    amount = int(args["amount"])
    reason = args.get("reason", "")
    p = state.player
    p.gold = max(0, p.gold + amount)
    if amount > 0:
        ui.event("GOLD", f"+{amount}gp ({reason}). Total: {p.gold}.")
    elif amount < 0:
        ui.event("GOLD", f"{amount}gp ({reason}). Total: {p.gold}.")
    return f"Gold changed by {amount} ({reason}). Player has {p.gold}gp."


def _exec_add_item(state: GameState, args: dict) -> str:
    name = args["name"]
    qty = int(args.get("quantity") or 1)
    existing = _find_item(state, name)
    if existing:
        existing["quantity"] = existing.get("quantity", 1) + qty
        msg = f"Added {qty}x {name} (now {existing['quantity']})."
    else:
        state.player.inventory.append({
            "name": name,
            "description": args.get("description", ""),
            "quantity": qty,
            "type": args.get("item_type", "misc"),
            "properties": args.get("properties") or {},
        })
        msg = f"Added {qty}x {name}."
    ui.event("ITEM+", f"{msg}")
    return msg


def _exec_remove_item(state: GameState, args: dict) -> str:
    name = args["name"]
    qty = int(args.get("quantity") or 1)
    existing = _find_item(state, name)
    if not existing:
        return f"Player does not have any {name}."
    held = existing.get("quantity", 1)
    unequipped_slots: list[str] = []
    if qty >= held:
        state.player.inventory.remove(existing)
        for slot, n in list(state.player.equipped.items()):
            if n.lower() == name.lower():
                del state.player.equipped[slot]
                unequipped_slots.append(slot)
        msg = f"Removed all {held}x {name}."
    else:
        existing["quantity"] = held - qty
        msg = f"Removed {qty}x {name} (remaining {existing['quantity']})."
    ui.event("ITEM-", f"{msg} ({args.get('reason', '')})")
    # If we just unequipped armor/shield, AC needs to recalculate.
    if unequipped_slots:
        _recompute_ac(state)
        msg += f" Unequipped from {', '.join(unequipped_slots)}; AC is now {state.player.ac}."
    return msg


def _exec_equip_item(state: GameState, args: dict) -> str:
    name = args["name"]
    slot = args["slot"]
    if not _find_item(state, name):
        return f"Player does not own {name}; cannot equip."
    state.player.equipped[slot] = name
    ui.event("EQUIP", f"{name} -> {slot}")
    # Recompute AC if relevant
    _recompute_ac(state)
    return f"Equipped {name} into {slot}. AC is now {state.player.ac}."


def _recompute_ac(state: GameState) -> None:
    p = state.player
    armor_name = p.equipped.get("armor")
    base_ac, dex_cap = 10, 99
    if armor_name:
        armor = _find_item(state, armor_name)
        if armor and "ac" in armor.get("properties", {}):
            base_ac = int(armor["properties"]["ac"])
            dex_cap = int(armor["properties"].get("dex_cap", 99))
    ac = base_ac + min(p.stat_mod("DEX"), dex_cap)
    shield_name = p.equipped.get("offhand")
    if shield_name:
        shield = _find_item(state, shield_name)
        if shield and shield.get("type") == "shield":
            ac += int(shield.get("properties", {}).get("ac_bonus", 2))
    p.ac = ac


def _exec_set_location(state: GameState, args: dict) -> str:
    name = args["name"]
    if name not in state.locations:
        state.locations[name] = {
            "region": args.get("region", "unknown"),
            "type": args.get("location_type", "other"),
            "description": args.get("description", ""),
            "discovered": True,
        }
        ui.event("DISCOVERED", f"{name} added to the world map.")
    else:
        state.locations[name]["discovered"] = True
        if args.get("description"):
            state.locations[name]["description"] = args["description"]
        if args.get("region"):
            state.locations[name]["region"] = args["region"]
        if args.get("location_type"):
            state.locations[name]["type"] = args["location_type"]
    state.player_location = name
    ui.event("MOVE", f"-> {name}")
    return f"Player is now in {name}."


def _exec_note_npc(state: GameState, args: dict) -> str:
    name = args["name"]
    npc = state.npcs.get(name, {
        "location": "", "role": "", "personality": "",
        "relationship": "neutral", "notes": "",
    })
    new_notes = args.get("notes")
    for k in ["location", "role", "personality", "relationship"]:
        if args.get(k):
            npc[k] = args[k]
    if new_notes:
        # Append rather than overwrite, so dossier accretes.
        sep = "\n" if npc.get("notes") else ""
        npc["notes"] = (npc.get("notes", "") + sep + new_notes).strip()
    state.npcs[name] = npc
    ui.event("NPC", f"{name} -- {npc.get('relationship', 'neutral')}")
    return f"NPC dossier for {name} updated."


def _exec_set_quest(state: GameState, args: dict) -> str:
    name = args["name"]
    quest = state.quests.get(name, {})
    if args.get("description"):
        quest["description"] = args["description"]
    quest["status"] = args.get("status", "active")
    if args.get("reward"):
        quest["reward"] = args["reward"]
    state.quests[name] = quest
    ui.event("QUEST", f"{name} [{quest['status']}]")
    return f"Quest '{name}' is now {quest['status']}."


def _exec_set_combat(state: GameState, args: dict) -> str:
    state.in_combat = bool(args["in_combat"])
    state.combat_summary = args.get("summary", "") if state.in_combat else ""
    ui.event("COMBAT", "engaged" if state.in_combat else "ended")
    return f"Combat state set to {state.in_combat}."


def _exec_journal(state: GameState, args: dict) -> str:
    entry = args["entry"].strip()
    if not entry:
        return "Empty journal entry; ignored."
    state.journal.append({"turn": state.turn, "text": entry})
    return f"Journal entry recorded ({len(state.journal)} total)."


def _exec_rest(state: GameState, args: dict) -> str:
    rest_type = args.get("rest_type", "short")
    p = state.player
    if rest_type == "long":
        p.hp = p.max_hp
        # Don't auto-clear conditions like 'cursed' that should be plot-driven;
        # the DM can still call set_condition afterward.
        p.conditions = [c for c in p.conditions if c not in {"poisoned", "frightened", "exhausted"}]
        ui.event("REST", "Long rest: HP fully restored, basic conditions cleared.")
        return "Player took a long rest. HP fully restored. Common conditions cleared."
    else:
        roll = dice.roll("1d8")
        heal = max(1, roll["total"] + p.stat_mod("CON"))
        before = p.hp
        p.hp = min(p.max_hp, p.hp + heal)
        ui.event("REST", f"Short rest: rolled {roll['detail']} +CON = {heal}. HP {before} -> {p.hp}.")
        return f"Player took a short rest. Healed {p.hp - before} HP. HP {p.hp}/{p.max_hp}."


def _exec_show_art(state: GameState, args: dict) -> str:
    art_text = args.get("art", "")
    if not art_text or not art_text.strip():
        return "ERROR: empty art."
    caption = args.get("caption", "") or ""
    subject = args.get("subject", "") or "scene"
    ui.art_block(art_text, caption=caption)
    return f"Rendered ASCII art for: {subject}."


def _exec_set_condition(state: GameState, args: dict) -> str:
    cond = args["condition"].lower()
    active = bool(args["active"])
    p = state.player
    if active and cond not in p.conditions:
        p.conditions.append(cond)
        ui.event("CONDITION", f"+{cond} ({args.get('reason', '')})")
        return f"Condition '{cond}' added."
    if not active and cond in p.conditions:
        p.conditions.remove(cond)
        ui.event("CONDITION", f"-{cond} ({args.get('reason', '')})")
        return f"Condition '{cond}' removed."
    return f"No change for condition '{cond}'."


EXECUTORS: dict[str, Callable[[GameState, dict], str]] = {
    "roll_dice": _exec_roll_dice,
    "change_hp": _exec_change_hp,
    "award_xp": _exec_award_xp,
    "change_gold": _exec_change_gold,
    "add_item": _exec_add_item,
    "remove_item": _exec_remove_item,
    "equip_item": _exec_equip_item,
    "set_location": _exec_set_location,
    "note_npc": _exec_note_npc,
    "set_quest": _exec_set_quest,
    "set_combat": _exec_set_combat,
    "journal": _exec_journal,
    "rest": _exec_rest,
    "set_condition": _exec_set_condition,
    "show_art": _exec_show_art,
}


def dispatch(state: GameState, name: str, args: dict) -> tuple[str, bool]:
    """Run a tool. Returns (result_text, ok)."""
    fn = EXECUTORS.get(name)
    if fn is None:
        return (f"ERROR: unknown tool '{name}'", False)
    try:
        return (fn(state, args or {}), True)
    except Exception as e:
        return (f"ERROR while running tool '{name}': {e}", False)
