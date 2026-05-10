"""End-to-end verification without hitting Bedrock.

Run: python verify.py

Exercises:
  - Character + state construction
  - Every tool dispatcher
  - Message-history sanitization (broken histories -> clean)
  - Atomic save / load round trip
  - DM agent loop (with a mocked Bedrock client) including tool calls
  - Resume: save mid-session, simulate process restart, continue
  - Error rollback: if Bedrock errors, message history stays in clean alternation

Exits 0 on success, 1 with a traceback on the first failure.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Force NO_COLOR for clean test output.
os.environ.setdefault("NO_COLOR", "1")

import dice
from character import CLASSES, Character
from state import GameState, sanitize_messages, safe_trim
from tools import dispatch
import dm as dm_mod


# --- helpers --------------------------------------------------------------

def make_test_character(name: str = "Aelor") -> Character:
    stats = {"STR": 16, "DEX": 12, "CON": 14, "INT": 10, "WIS": 10, "CHA": 10}
    cls = CLASSES["Fighter"]
    con_mod = (stats["CON"] - 10) // 2
    return Character(
        name=name,
        race="Human",
        char_class="Fighter",
        background="Disgraced soldier seeking redemption.",
        level=1,
        xp=0,
        max_hp=cls["hit_die"] + con_mod,
        hp=cls["hit_die"] + con_mod,
        ac=18,
        gold=25,
        stats=stats,
        inventory=[
            {"name": n, "description": d, "quantity": q, "type": t, "properties": p}
            for (n, d, q, t, p) in cls["starting_inventory"]
        ],
        equipped={"mainhand": "Longsword", "armor": "Chainmail", "offhand": "Wooden shield"},
    )


class FakeBedrockClient:
    """A scriptable stand-in for boto3's bedrock-runtime client.

    Construct with a list of canned responses (in Bedrock Converse format).
    Each call to converse() pops the next response. If a response in the
    queue is an Exception instance, it's raised instead.
    """

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeBedrockClient ran out of responses")
        nxt = self.responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def text_resp(text: str) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
    }


def tool_resp(tool_uses: list[dict], text: str = "") -> dict:
    """tool_uses: list of {'id', 'name', 'input'}."""
    content: list = []
    if text:
        content.append({"text": text})
    for tu in tool_uses:
        content.append({
            "toolUse": {"toolUseId": tu["id"], "name": tu["name"], "input": tu["input"]}
        })
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use",
    }


def make_dm_with_responses(responses: list) -> "dm_mod.DungeonMaster":
    """Build a DungeonMaster but bypass real boto3."""
    fake = FakeBedrockClient(responses)
    dm = dm_mod.DungeonMaster.__new__(dm_mod.DungeonMaster)
    dm.model_id = "fake-model"
    dm.region = "fake-region"
    dm.profile = None
    dm.client = fake
    return dm, fake


# --- assertions -----------------------------------------------------------

PASSED = 0
FAILED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED += 1
        print(f"  FAIL  {label}  {detail}")


# --- tests ----------------------------------------------------------------

def test_character_and_state() -> None:
    print("\n[1] character + state construction")
    char = make_test_character()
    state = GameState.new(char)
    check("character HP set from class+CON", state.player.max_hp == 12 and state.player.hp == 12)
    check("seed locations present", "Stonehaven" in state.locations and "Mt. Kaeloth" in state.locations)
    check("seed NPCs present", "Garrick Stoneward" in state.npcs)
    check("starts in Stonehaven", state.player_location == "Stonehaven")


def test_tools() -> None:
    print("\n[2] tool dispatch")
    char = make_test_character()
    state = GameState.new(char)

    cases: list[tuple[str, dict]] = [
        ("roll_dice", {"dice_notation": "1d20", "modifier": 3, "reason": "Stealth", "dc": 15}),
        ("roll_dice", {"dice_notation": "2d6+2", "reason": "Damage"}),
        ("change_hp", {"amount": -4, "reason": "Bandit hit"}),
        ("change_hp", {"amount": 2, "reason": "Healing"}),
        ("award_xp", {"amount": 350, "reason": "Killed two wolves"}),  # crosses L2
        ("change_gold", {"amount": -10, "reason": "Bought rations"}),
        ("add_item", {"name": "Healing potion", "description": "2d4+2 HP", "quantity": 2, "item_type": "consumable"}),
        ("add_item", {"name": "Healing potion", "description": "stack", "quantity": 1, "item_type": "consumable"}),
        ("remove_item", {"name": "Healing potion", "quantity": 1, "reason": "Used"}),
        ("remove_item", {"name": "Wooden shield", "reason": "Smashed"}),  # should drop AC
        ("equip_item", {"name": "Longsword", "slot": "mainhand"}),
        ("set_location", {"name": "Greymoor"}),
        ("set_location", {"name": "Bramblefield Camp", "description": "Bandit camp", "region": "Central Ashvale", "location_type": "wilderness"}),
        ("note_npc", {"name": "Rook", "location": "Bramblefield Camp", "role": "Bandit captain", "personality": "Mocking", "relationship": "hostile", "notes": "Copper signet ring."}),
        ("note_npc", {"name": "Rook", "notes": "Spared by player.", "relationship": "wary"}),
        ("set_quest", {"name": "Slay Vorthrax", "description": "Kill the dragon", "status": "active", "reward": "50000gp"}),
        ("set_combat", {"in_combat": True, "summary": "2 bandits"}),
        ("set_combat", {"in_combat": False}),
        ("journal", {"entry": "Met Garrick at the Stag & Saddle."}),
        ("rest", {"rest_type": "short"}),
        ("rest", {"rest_type": "long"}),
        ("set_condition", {"condition": "blessed", "active": True, "reason": "Cleric"}),
        ("set_condition", {"condition": "blessed", "active": False, "reason": "ended"}),
        ("show_art", {"art": "  /\\___/\\\n ( o.o  )\n  > ^ <\n", "caption": "A wary fox in the brush.", "subject": "fox"}),
        ("show_art", {"art": "", "subject": "empty"}),  # should error gracefully
    ]
    fail_names: list[str] = []
    for name, args in cases:
        text, ok = dispatch(state, name, args)
        # show_art with empty input is expected to "fail" the dispatcher's
        # success flag (returns ERROR string but doesn't raise).
        if name == "show_art" and not args.get("art"):
            check("show_art rejects empty input", text.startswith("ERROR") and ok is True)
            continue
        if not ok:
            fail_names.append(name)
    check("all tools executed", not fail_names, f"failed={fail_names}")
    check("player leveled to 2", state.player.level == 2, f"level={state.player.level} xp={state.player.xp}")
    check("NPC notes accreted", "Copper signet" in state.npcs["Rook"]["notes"] and "Spared" in state.npcs["Rook"]["notes"])
    check("relationship updated", state.npcs["Rook"]["relationship"] == "wary")
    check("AC recomputed after shield removed", state.player.ac == 16, f"ac={state.player.ac}")
    check("location is the latest set", state.player_location == "Bramblefield Camp")
    check("location was added to map", "Bramblefield Camp" in state.locations)
    check("quest added", "Slay Vorthrax" in state.quests)
    check("journal entry present", any("Stag & Saddle" in j["text"] for j in state.journal))


def test_dice() -> None:
    print("\n[3] dice")
    for n in ["1d20", "d20", "2d6+3", "1d8-1"]:
        r = dice.roll(n)
        check(f"dice {n} parses", isinstance(r["total"], int))


def test_save_load_round_trip() -> None:
    print("\n[4] save / load round trip")
    char = make_test_character("Resumea")
    state = GameState.new(char)
    dispatch(state, "change_hp", {"amount": -3, "reason": "Test"})
    dispatch(state, "award_xp", {"amount": 50, "reason": "Test"})
    dispatch(state, "set_location", {"name": "Greymoor"})
    dispatch(state, "note_npc", {"name": "Captain Hadrik Brenn", "relationship": "ally", "notes": "Briefed on the dragon."})
    dispatch(state, "journal", {"entry": "Reached Greymoor and met Hadrik."})
    # Add a clean exchange to messages
    state.messages.append({"role": "user", "content": [{"text": "I look around."}]})
    state.messages.append({"role": "assistant", "content": [{"text": "You see the gate."}]})

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "save.json"
        state.save(p)
        check("save file exists", p.exists())
        check("no .tmp left over (atomic save)", not p.with_suffix(".json.tmp").exists())
        loaded = GameState.load(p)
        check("player name preserved", loaded.player.name == "Resumea")
        check("HP preserved", loaded.player.hp == state.player.hp)
        check("XP preserved", loaded.player.xp == state.player.xp)
        check("location preserved", loaded.player_location == "Greymoor")
        check("custom NPC notes preserved", "Briefed" in loaded.npcs["Captain Hadrik Brenn"]["notes"])
        check("journal preserved", any("Greymoor" in j["text"] for j in loaded.journal))
        check("messages preserved", len(loaded.messages) == 2)


def test_message_sanitization() -> None:
    print("\n[5] message sanitization (no broken histories survive)")

    # Case A: trailing assistant tool_use with no toolResult -> drop both that
    # message and the user that triggered it.
    a = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "ok"}]},
        {"role": "user", "content": [{"text": "do the thing"}]},
        {"role": "assistant", "content": [{"text": "rolling..."}, {"toolUse": {"toolUseId": "t1", "name": "roll_dice", "input": {"dice_notation": "1d20", "reason": "x"}}}]},
    ]
    cleaned = sanitize_messages(a)
    check("dangling tool_use dropped",
          len(cleaned) == 2 and cleaned[-1]["role"] == "assistant" and all("toolUse" not in b for b in cleaned[-1]["content"]),
          f"len={len(cleaned)}")

    # Case B: trailing user message (Bedrock errored mid-call) -> drop.
    b = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "yo"}]},
        {"role": "user", "content": [{"text": "next"}]},
    ]
    cleaned = sanitize_messages(b)
    check("trailing user dropped", len(cleaned) == 2 and cleaned[-1]["role"] == "assistant")

    # Case C: history starts with an orphan toolResult -> drop until clean.
    c = [
        {"role": "user", "content": [{"toolResult": {"toolUseId": "x", "content": [{"text": "r"}]}}]},
        {"role": "assistant", "content": [{"text": "ok"}]},
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "yo"}]},
    ]
    cleaned = sanitize_messages(c)
    check("leading orphan toolResult dropped", cleaned and cleaned[0]["role"] != "user" or (cleaned[0]["role"] == "user" and any("text" in b for b in cleaned[0]["content"])))

    # Case D: safe_trim never splits a tool pair.
    d = [
        {"role": "user", "content": [{"text": "u1"}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "tA", "name": "x", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "tA", "content": [{"text": "r"}]}}]},
        {"role": "assistant", "content": [{"text": "ok"}]},
        {"role": "user", "content": [{"text": "u2"}]},
        {"role": "assistant", "content": [{"text": "great"}]},
    ]
    trimmed = safe_trim(d, max_keep=3)
    # max_keep=3 would split at index 3 (assistant text), but that's a clean
    # post-tool-pair boundary -- but actually our function looks for a clean
    # USER-with-text. The next clean start is index 4 ("u2").
    check("safe_trim starts at clean user boundary",
          trimmed[0]["role"] == "user" and trimmed[0]["content"][0].get("text") == "u2",
          f"first={trimmed[0]}")


def test_dm_loop_with_tools() -> None:
    print("\n[6] DM agent loop with tool calls (mocked Bedrock)")
    char = make_test_character()
    state = GameState.new(char)

    # Scripted: DM rolls perception, then narrates with damage + journal, then ends.
    responses = [
        tool_resp([
            {"id": "tu1", "name": "roll_dice",
             "input": {"dice_notation": "1d20", "modifier": 0, "reason": "Perception", "dc": 12}},
        ], text="You scan the road ahead."),
        tool_resp([
            {"id": "tu2", "name": "change_hp", "input": {"amount": -3, "reason": "Sprung trap"}},
            {"id": "tu3", "name": "journal", "input": {"entry": "Tripped a pit trap on the road."}},
        ]),
        text_resp("A pit opens beneath you. You catch the lip and pull yourself out, scraped but alive. The road continues. What now?"),
    ]
    dm, fake = make_dm_with_responses(responses)

    dm.take_turn(state, "I scan the road ahead for traps.")

    check("turn counter advanced", state.turn == 1)
    check("DM was called 3 times (one per loop iter)", len(fake.calls) == 3)
    check("HP reduced", state.player.hp == state.player.max_hp - 3)
    check("journal got an entry", any("pit trap" in j["text"] for j in state.journal))
    # Messages should end with the final text response (assistant)
    check("messages end with assistant text",
          state.messages[-1]["role"] == "assistant"
          and any("text" in b for b in state.messages[-1]["content"]))
    # Alternation invariant
    roles = [m["role"] for m in state.messages]
    check("messages alternate user/assistant", all(roles[i] != roles[i+1] for i in range(len(roles)-1)),
          f"roles={roles}")


def test_save_resume_continues_cleanly() -> None:
    print("\n[7] save -> simulated restart -> resume continues with new turn")
    char = make_test_character("Saver")
    state = GameState.new(char)

    # First turn: simple narration, no tools.
    dm1, _ = make_dm_with_responses([text_resp("You enter the inn. It smells of pipe smoke.")])
    dm1.take_turn(state, "I push open the door of the inn.")

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "save.json"
        state.save(p)

        # Simulate restart: throw the in-memory state away.
        del state
        loaded = GameState.load(p)

        # Second turn after resume: tool + narration.
        dm2, fake = make_dm_with_responses([
            tool_resp([
                {"id": "tu_g", "name": "change_gold", "input": {"amount": -2, "reason": "Bought a tankard"}},
                {"id": "tu_j", "name": "journal", "input": {"entry": "Bought a drink at the Stag & Saddle."}},
            ]),
            text_resp("The barkeep slides you a foaming tankard."),
        ])
        dm2.take_turn(loaded, "I order an ale.")

        check("resumed turn ran", loaded.turn == 2)
        check("gold deducted on resumed turn", loaded.player.gold == 23)
        check("journal grew on resumed turn", any("Bought a drink" in j["text"] for j in loaded.journal))
        # Messages still alternating after resume + new turn.
        roles = [m["role"] for m in loaded.messages]
        check("resumed history alternates", all(roles[i] != roles[i+1] for i in range(len(roles)-1)),
              f"roles={roles}")

        # And we can save again.
        loaded.save(p)
        again = GameState.load(p)
        check("save again -> load round trips", again.turn == 2 and again.player.gold == 23)


def test_dm_error_rollback() -> None:
    print("\n[8] error rollback keeps history clean")
    char = make_test_character("Rollback")
    state = GameState.new(char)

    # First, a normal turn so we have a baseline.
    dm1, _ = make_dm_with_responses([text_resp("Trees, mud, the smell of rain.")])
    dm1.take_turn(state, "I look around.")
    baseline_msgs = list(state.messages)
    baseline_turn = state.turn

    # Now a failing call.
    class FakeError(RuntimeError):
        pass
    dm2, _ = make_dm_with_responses([FakeError("Bedrock 503")])
    raised = False
    try:
        dm2.take_turn(state, "I yell into the void.")
    except FakeError:
        raised = True
    check("error propagated", raised)
    check("messages restored to baseline", state.messages == baseline_msgs,
          f"len now={len(state.messages)} baseline={len(baseline_msgs)}")
    check("turn counter restored", state.turn == baseline_turn)

    # And after rollback the next turn works.
    dm3, _ = make_dm_with_responses([text_resp("The void declines comment.")])
    dm3.take_turn(state, "Try again.")
    check("recovered turn ran", state.turn == baseline_turn + 1)
    roles = [m["role"] for m in state.messages]
    check("history still alternates", all(roles[i] != roles[i+1] for i in range(len(roles)-1)),
          f"roles={roles}")


def test_force_narration_when_loop_caps() -> None:
    """If the model uses tools 12 times in a row, we must force a closing
    narration without appending two consecutive user messages."""
    print("\n[9] tool-loop cap forces a clean closing narration")
    char = make_test_character()
    state = GameState.new(char)

    # 12 tool_use responses (the cap) followed by a final text response.
    # The agent loop should hit the `else` branch and call _converse with
    # with_tools=False, returning the final text.
    responses = []
    for i in range(12):
        responses.append(tool_resp([
            {"id": f"tu{i}", "name": "journal", "input": {"entry": f"loop iter {i}"}},
        ]))
    responses.append(text_resp("(Closing narration after force-end.)"))

    dm, fake = make_dm_with_responses(responses)
    dm.take_turn(state, "Do twelve things at once.")

    # We made 12 tool calls plus 1 forced final = 13 converse calls.
    check("13 Converse calls", len(fake.calls) == 13, f"got {len(fake.calls)}")
    # The forced final call must NOT include toolConfig.
    last_call = fake.calls[-1]
    check("force-end call had no toolConfig", "toolConfig" not in last_call,
          f"keys={list(last_call.keys())}")
    # History must end on assistant text (not user toolResult).
    last_msg = state.messages[-1]
    check("history ends on assistant text",
          last_msg["role"] == "assistant"
          and any("text" in b for b in last_msg["content"]))
    # Alternation invariant.
    roles = [m["role"] for m in state.messages]
    check("alternation preserved across forced end",
          all(roles[i] != roles[i+1] for i in range(len(roles)-1)),
          f"roles tail={roles[-6:]}")


def test_save_creates_parent_dir() -> None:
    print("\n[10] save creates missing parent directories")
    char = make_test_character()
    state = GameState.new(char)
    with tempfile.TemporaryDirectory() as td:
        nested = Path(td) / "deep" / "nested" / "dir" / "save.json"
        state.save(nested)
        check("nested save written", nested.exists())
        again = GameState.load(nested)
        check("nested save loadable", again.player.name == state.player.name)


def test_partial_stats_load() -> None:
    print("\n[11] character.from_dict tolerates partial / typed stats")
    bad = {
        "name": "Frag",
        "race": "Elf",
        "char_class": "Wizard",
        "background": "",
        # Only 2 stats present; rest should default to 10.
        "stats": {"INT": "16", "DEX": 14},
    }
    c = Character.from_dict(bad)
    check("missing stats defaulted to 10", c.stats["STR"] == 10 and c.stats["CON"] == 10)
    check("string stat coerced to int", c.stats["INT"] == 16)
    # And stat_mod should not raise for any stat.
    for s in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
        c.stat_mod(s)
    check("stat_mod safe for all six abilities", True)


# --- main -----------------------------------------------------------------

def main() -> int:
    tests = [
        test_character_and_state,
        test_tools,
        test_dice,
        test_save_load_round_trip,
        test_message_sanitization,
        test_dm_loop_with_tools,
        test_save_resume_continues_cleanly,
        test_dm_error_rollback,
        test_force_narration_when_loop_caps,
        test_save_creates_parent_dir,
        test_partial_stats_load,
    ]
    for t in tests:
        try:
            t()
        except Exception:
            print(f"\n  EXCEPTION in {t.__name__}:")
            traceback.print_exc()
            global FAILED
            FAILED += 1
    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
