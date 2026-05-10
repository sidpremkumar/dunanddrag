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
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content") or []
    has_text = any("text" in b and b["text"].strip() for b in content)
    has_tool_use = any("toolUse" in b for b in content)
    return has_text and not has_tool_use


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
    in_combat: bool = False
    combat_summary: str = ""

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
            "in_combat": self.in_combat,
            "combat_summary": self.combat_summary,
            "schema_version": 1,
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
            in_combat=d.get("in_combat", False),
            combat_summary=d.get("combat_summary", ""),
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


def _fmt_journal(journal: list[dict], n: int = 20) -> str:
    if not journal:
        return "  (the campaign has just begun)"
    return "\n".join(f"  - turn {e['turn']}: {e['text']}" for e in journal[-n:])


def render_state_snapshot(state: GameState) -> str:
    p = state.player
    stats_line = "  ".join(f"{s} {p.stats[s]:>2} ({p.stat_mod(s):+d})"
                           for s in ["STR", "DEX", "CON", "INT", "WIS", "CHA"])
    location = state.locations.get(state.player_location, {})
    return f"""\
# CURRENT PLAYER
Name: {p.name}
Race/Class: {p.race} {p.char_class}, level {p.level}
HP: {p.hp}/{p.max_hp}     AC: {p.ac}     Gold: {p.gold}     XP: {p.xp}
Proficiency: +{p.proficiency()}
Stats: {stats_line}
Conditions: {', '.join(p.conditions) if p.conditions else 'none'}
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

# ACTIVE QUESTS
{_fmt_quests(state.quests)}

# KNOWN NPCS (your dossier -- update as relationships change)
{_fmt_npcs(state.npcs)}

# WORLD MAP
{_fmt_locations(state.locations)}

# RECENT JOURNAL ENTRIES (your long-term memory)
{_fmt_journal(state.journal, 25)}

# TURN
This is turn {state.turn + 1} of the campaign.
"""
