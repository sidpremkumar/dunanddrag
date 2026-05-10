"""Game state: player, world, journal, and Bedrock message history.

Persisted as JSON. The DM is given a fresh snapshot of state every turn
(via the system prompt), so the model never has to remember state across
turns -- just narrative context.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from character import Character
from world import SEED_LOCATIONS, SEED_NPCS

DEFAULT_SAVE_PATH = Path("save.json")
# We trim message history to this many entries before each save to keep
# both context budgets and save files reasonable. The journal carries
# long-term memory.
MAX_HISTORY_MESSAGES = 60


def _is_clean_user_text(msg: dict) -> bool:
    """A user message that contains text and no toolResult -- a safe trim/start point."""
    if msg.get("role") != "user":
        return False
    content = msg.get("content") or []
    has_text = any("text" in b for b in content)
    has_tool_result = any("toolResult" in b for b in content)
    return has_text and not has_tool_result


def _is_clean_assistant_close(msg: dict) -> bool:
    """A trailing assistant message is 'clean' iff it has no orphan toolUse.
    An empty/whitespace text block is fine -- it just means no narration to
    display. Stripping such a message would cascade past valid earlier turns
    (because their assistant message contains a tool_use that is, however,
    properly paired with a following toolResult)."""
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content") or []
    return not any("toolUse" in b for b in content)


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """Make a message history safe to send to Bedrock Converse.

    Strategy: trim from both ends until invariants hold.
      - Tail must be an assistant message with non-empty text and no toolUse.
      - Head must be a user message with text and no toolResult.
    Middle alternation is guaranteed by take_turn (which is the only way new
    messages get appended). Sanitize is defense-in-depth for crashes.
    """
    out = list(messages)
    # Strip tail until clean assistant text close.
    while out and not _is_clean_assistant_close(out[-1]):
        out.pop()
    # Strip head until clean user-text start.
    while out:
        first = out[0]
        if (
            first.get("role") == "user"
            and any("text" in b for b in first.get("content", []))
            and not any("toolResult" in b for b in first.get("content", []))
        ):
            break
        out.pop(0)
    return out


def safe_trim(messages: list[dict], max_keep: int) -> list[dict]:
    """Trim from the start to at most max_keep messages, but only at a clean
    boundary (a user message with text content, not toolResult). Never split
    a tool_use/toolResult pair."""
    if len(messages) <= max_keep:
        return messages
    start = len(messages) - max_keep
    while start < len(messages) and not _is_clean_user_text(messages[start]):
        start += 1
    return messages[start:]


@dataclass
class GameState:
    player: Character
    player_location: str = "Stonehaven"
    locations: dict[str, dict] = field(default_factory=dict)
    npcs: dict[str, dict] = field(default_factory=dict)
    quests: dict[str, dict] = field(default_factory=dict)
    journal: list[dict] = field(default_factory=list)  # [{ "turn": int, "text": str }]
    messages: list[dict] = field(default_factory=list)  # Bedrock Converse format
    turn: int = 0
    # In-game day counter. Day 1 is start. Long rest auto-advances by 1.
    # The DM can also call advance_time(days=N) for travel / montages.
    day: int = 1
    in_combat: bool = False
    combat_summary: str = ""
    # Pets / animal companions / hireling-tier allies. Each entry:
    #   name, kind, hp, max_hp, ac, attack_bonus, damage_dice,
    #   friendliness (0-100), in_party (bool), notes, inventory (list[dict])
    companions: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls, player: Character) -> "GameState":
        return cls(
            player=player,
            player_location="Stonehaven",
            locations=copy.deepcopy(SEED_LOCATIONS),
            npcs=copy.deepcopy(SEED_NPCS),
            quests={},
            journal=[],
            messages=[],
            turn=0,
        )

    def to_dict(self) -> dict:
        return {
            "player": self.player.to_dict(),
            "player_location": self.player_location,
            "locations": self.locations,
            "npcs": self.npcs,
            "quests": self.quests,
            "journal": self.journal,
            "messages": safe_trim(self.messages, MAX_HISTORY_MESSAGES),
            "turn": self.turn,
            "day": self.day,
            "in_combat": self.in_combat,
            "combat_summary": self.combat_summary,
            "companions": self.companions,
            "schema_version": 3,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        return cls(
            player=Character.from_dict(d["player"]),
            player_location=d.get("player_location", "Stonehaven"),
            locations=d.get("locations", copy.deepcopy(SEED_LOCATIONS)),
            npcs=d.get("npcs", copy.deepcopy(SEED_NPCS)),
            quests=d.get("quests", {}),
            journal=d.get("journal", []),
            # Sanitize on load so an interrupted save can never wedge resume.
            messages=sanitize_messages(d.get("messages", [])),
            turn=d.get("turn", 0),
            day=int(d.get("day", 1)),
            in_combat=d.get("in_combat", False),
            combat_summary=d.get("combat_summary", ""),
            companions=d.get("companions", []),
        )

    def save(self, path: Path = DEFAULT_SAVE_PATH) -> None:
        # Atomic write: write to a temp file then rename, so an interrupted
        # save cannot leave a half-written/corrupted save file.
        path = Path(path)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path = DEFAULT_SAVE_PATH) -> "GameState":
        return cls.from_dict(json.loads(Path(path).read_text()))


# --- Snapshot rendering for the system prompt ----------------------------


def _fmt_inventory(inv: list[dict]) -> str:
    if not inv:
        return "  (empty)"
    out = []
    for it in inv:
        qty = f" x{it['quantity']}" if it.get("quantity", 1) > 1 else ""
        props = ""
        if it.get("properties"):
            kv = ", ".join(f"{k}={v}" for k, v in it["properties"].items())
            if kv:
                props = f" ({kv})"
        out.append(f"  - {it['name']}{qty}{props} -- {it.get('description', '')}")
    return "\n".join(out)


def _fmt_equipped(eq: dict) -> str:
    if not eq:
        return "  (none)"
    return "\n".join(f"  - {slot}: {name}" for slot, name in eq.items())


def _fmt_locations(locs: dict) -> str:
    out = []
    for name, l in locs.items():
        flag = "[discovered]" if l.get("discovered") else "[rumored]"
        out.append(f"  - {name} {flag} ({l.get('type', '?')}, {l.get('region', '?')}): {l.get('description', '')}")
    return "\n".join(out) or "  (none)"


def _fmt_npcs(npcs: dict) -> str:
    if not npcs:
        return "  (none yet)"
    out = []
    for name, n in npcs.items():
        out.append(
            f"  - {name} @ {n.get('location', '?')} -- {n.get('role', '?')}\n"
            f"      personality: {n.get('personality', '')}\n"
            f"      relationship: {n.get('relationship', 'neutral')}\n"
            f"      notes: {n.get('notes', '') or '(none)'}"
        )
    return "\n".join(out)


def _fmt_quests(quests: dict) -> str:
    if not quests:
        return "  (none)"
    out = []
    for name, q in quests.items():
        out.append(f"  - {name} [{q.get('status', 'active')}]: {q.get('description', '')}"
                   + (f"  (reward: {q['reward']})" if q.get("reward") else ""))
    return "\n".join(out)


def friendliness_tier(score: int) -> str:
    """0-100 friendliness mapped to a named tier."""
    s = max(0, min(100, int(score)))
    if s < 20:
        return "wary"
    if s < 40:
        return "neutral"
    if s < 60:
        return "friendly"
    if s < 80:
        return "bonded"
    return "devoted"


def _fmt_companion_inv(inv: list[dict]) -> str:
    if not inv:
        return "(nothing)"
    parts = []
    for it in inv:
        qty = f" x{it['quantity']}" if it.get("quantity", 1) > 1 else ""
        parts.append(f"{it['name']}{qty}")
    return ", ".join(parts)


def _fmt_companions(comps: list[dict]) -> str:
    if not comps:
        return "  (none)"
    out = []
    in_party = [c for c in comps if c.get("in_party", True)]
    away = [c for c in comps if not c.get("in_party", True)]
    for c in in_party:
        f_score = int(c.get("friendliness", 50))
        tier = friendliness_tier(f_score)
        atk = c.get("attack_bonus")
        atk_s = f"+{atk}" if isinstance(atk, int) else "n/a"
        hp = int(c.get("hp", 0))
        max_hp = int(c.get("max_hp", 0))
        # Downed = HP 0; flag it loudly so the DM doesn't roll attacks
        # for an unconscious companion. Bloodied = at or below half HP.
        if hp <= 0:
            status = "  ** DOWNED -- cannot act; revive with update_companion(hp_delta=+N) **"
        elif max_hp > 0 and hp <= max_hp // 2:
            status = "  (bloodied)"
        else:
            status = ""
        out.append(
            f"  - {c['name']} ({c.get('kind', 'companion')}) "
            f"HP {hp}/{max_hp}{status}  "
            f"AC {c.get('ac', 10)}  atk {atk_s}  dmg {c.get('damage_dice', '-')}  "
            f"friendliness {f_score}/100 ({tier})\n"
            f"      carries: {_fmt_companion_inv(c.get('inventory', []))}\n"
            f"      notes: {c.get('notes', '') or '(none)'}"
        )
    if away:
        out.append("  -- not currently in party --")
        for c in away:
            out.append(f"  - {c['name']} ({c.get('kind', 'companion')}) -- {c.get('notes', '') or 'away'}")
    return "\n".join(out)


def _fmt_journal(journal: list[dict], n: int = 20) -> str:
    if not journal:
        return "  (the campaign has just begun)"
    return "\n".join(f"  - turn {e['turn']}: {e['text']}" for e in journal[-n:])


def render_state_snapshot(state: GameState) -> str:
    p = state.player
    stats_line = "  ".join(f"{s} {p.stats[s]:>2} ({p.stat_mod(s):+d})"
                           for s in ["STR", "DEX", "CON", "INT", "WIS", "CHA"])
    location = state.locations.get(state.player_location, {})
    # Spell slots line: only show for casters (non-empty spell_slots_max).
    if p.spell_slots_max:
        slot_strs = [f"L{lvl} {p.spell_slots.get(lvl, 0)}/{p.spell_slots_max[lvl]}"
                     for lvl in sorted(p.spell_slots_max.keys())]
        spell_slots_line = f"Spell slots: {'  '.join(slot_strs)}\n"
    else:
        spell_slots_line = ""
    # HP-0 player flag: mirror the companion DOWNED treatment so the DM
    # never tries to roll an attack for an unconscious hero.
    if p.hp <= 0:
        hp_flag = ("\n** UNCONSCIOUS -- HP is 0; the player cannot act, attack, "
                   "or cast until healed (change_hp +N) or revived. **")
    else:
        hp_flag = ""
    return f"""\
# CURRENT PLAYER
Name: {p.name}
Race/Class: {p.race} {p.char_class}, level {p.level}
HP: {p.hp}/{p.max_hp}     AC: {p.ac}     Gold: {p.gold}     XP: {p.xp}{hp_flag}
Proficiency: +{p.proficiency()}
Stats: {stats_line}
{spell_slots_line}Conditions: {', '.join(p.conditions) if p.conditions else 'none'}
Background: {p.background}

Inventory:
{_fmt_inventory(p.inventory)}

Equipped:
{_fmt_equipped(p.equipped)}

# CURRENT LOCATION
{state.player_location} ({location.get('type', '?')}, {location.get('region', '?')})
{location.get('description', '')}

# COMBAT
{('IN COMBAT: ' + state.combat_summary) if state.in_combat else 'Not currently in combat.'}

# COMPANIONS (pets / animal allies / hirelings; they act on the player's initiative)
{_fmt_companions(state.companions)}

# ACTIVE QUESTS
{_fmt_quests(state.quests)}

# KNOWN NPCS (your dossier -- update as relationships change)
{_fmt_npcs(state.npcs)}

# WORLD MAP
{_fmt_locations(state.locations)}

# RECENT JOURNAL ENTRIES (your long-term memory)
{_fmt_journal(state.journal, 25)}

# TURN & TIME
Turn {state.turn + 1}.  Day {state.day} of the campaign.
"""
