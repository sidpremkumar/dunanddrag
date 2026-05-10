"""Vorthrax the Crimson -- a CLI D&D-style game with an LLM Dungeon Master.

Entry point. Usage:

    python game.py            # continue if save.json exists, else new
    python game.py --new      # force a new campaign (overwrites save)
    python game.py --save other.json

Slash commands during play:
    /help        list these commands
    /stats       full character sheet
    /inventory   list inventory and equipment
    /journal     show recent journal entries
    /quests      show quest log
    /map         show discovered locations
    /save        save now (also auto-saves every turn)
    /quit        save and exit
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import character as char_mod
import ui
from dm import DungeonMaster
from state import GameState
from world import CAMPAIGN_OPENING, CAMPAIGN_TITLE


HELP_TEXT = """\
  /help        list these commands
  /stats       full character sheet
  /inventory   list inventory and equipment
  /journal     show recent journal entries
  /quests      show quest log
  /map         show discovered locations
  /save        save now (also auto-saves every turn)
  /quit        save and exit

Anything else is sent to the Dungeon Master. Be specific. The DM
voices the world; you voice your character. You can speak in
quotes, describe actions, ask questions, etc.
"""


def _print_inventory(state: GameState) -> None:
    p = state.player
    ui.section("Equipped")
    if not p.equipped:
        print("  (none)")
    for slot, name in p.equipped.items():
        print(f"  - {slot}: {name}")
    ui.section("Inventory")
    if not p.inventory:
        print("  (empty)")
    for it in p.inventory:
        qty = f" x{it['quantity']}" if it.get("quantity", 1) > 1 else ""
        print(f"  - {it['name']}{qty} -- {it.get('description', '')}")


def _print_journal(state: GameState, n: int = 25) -> None:
    ui.section("Journal")
    if not state.journal:
        print("  (no entries yet)")
        return
    for e in state.journal[-n:]:
        print(f"  - turn {e['turn']}: {e['text']}")


def _print_quests(state: GameState) -> None:
    ui.section("Quests")
    if not state.quests:
        print("  (no quests yet)")
        return
    for name, q in state.quests.items():
        print(f"  - {name} [{q.get('status', 'active')}]: {q.get('description', '')}"
              + (f"  (reward: {q['reward']})" if q.get("reward") else ""))


def _print_map(state: GameState) -> None:
    ui.section("World Map")
    discovered = [(n, l) for n, l in state.locations.items() if l.get("discovered")]
    rumored = [(n, l) for n, l in state.locations.items() if not l.get("discovered")]
    print("  Discovered:")
    if not discovered:
        print("    (none)")
    for n, l in discovered:
        print(f"    - {n} ({l.get('type', '?')}, {l.get('region', '?')}): {l.get('description', '')}")
    if rumored:
        print("  Rumored:")
        for n, l in rumored:
            print(f"    - {n} ({l.get('region', '?')}): {l.get('description', '')}")


def handle_command(cmd: str, state: GameState, save_path: Path) -> bool:
    """Returns True if the command was handled (don't send to DM)."""
    cmd = cmd.strip().lower()
    if cmd in ("/help", "/?", "/h"):
        print(HELP_TEXT)
    elif cmd in ("/stats", "/sheet", "/character"):
        char_mod.print_sheet(state.player)
    elif cmd in ("/inv", "/inventory", "/i"):
        _print_inventory(state)
    elif cmd in ("/journal", "/log"):
        _print_journal(state)
    elif cmd in ("/quests", "/quest", "/q"):
        _print_quests(state)
    elif cmd in ("/map", "/locations"):
        _print_map(state)
    elif cmd == "/save":
        state.save(save_path)
        ui.success(f"Saved to {save_path}.")
    elif cmd in ("/quit", "/exit", "/q!"):
        state.save(save_path)
        ui.success(f"Saved to {save_path}. Farewell.")
        sys.exit(0)
    else:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{CAMPAIGN_TITLE} -- a CLI D&D game with an LLM DM.")
    parser.add_argument("--new", action="store_true", help="Start a new campaign (overwrites save).")
    parser.add_argument("--save", default="save.json", help="Path to save file (default: save.json).")
    parser.add_argument("--region", default=None, help="AWS region (default: env or us-west-2).")
    parser.add_argument("--model", default=None, help="Bedrock model id (default: env or Claude Opus 4.5 inference profile).")
    args = parser.parse_args()

    save_path = Path(args.save)

    ui.banner(CAMPAIGN_TITLE, "A solo D&D-style campaign with an AI Dungeon Master")

    # Load or create
    state: GameState
    is_new = False
    if save_path.exists() and not args.new:
        choice = ui.prompt(f"Save file found at {save_path}. [c]ontinue or [n]ew? ").strip().lower()
        if choice in ("n", "new"):
            is_new = True
        else:
            try:
                state = GameState.load(save_path)
                ui.success(f"Loaded {state.player.name}, level {state.player.level} {state.player.race} {state.player.char_class} -- turn {state.turn}, in {state.player_location}.")
            except Exception as e:
                ui.error(f"Failed to load save: {e}")
                if ui.prompt("Start fresh? [y/N] ").strip().lower() != "y":
                    sys.exit(1)
                is_new = True
    else:
        is_new = True

    if is_new:
        char = char_mod.create_character()
        state = GameState.new(char)
        if ui.prompt("\nReady to begin? [Y/n] ").strip().lower() == "n":
            ui.system("Aborted before saving.")
            sys.exit(0)
        state.save(save_path)

    # Init DM
    try:
        dm = DungeonMaster(model_id=args.model, region=args.region)
    except Exception as e:
        ui.error(f"Failed to initialize Bedrock client: {e}")
        ui.system("Make sure your AWS credentials are configured and the model id is correct.")
        sys.exit(1)

    ui.system(f"DM model: {dm.model_id}  region: {dm.region}")

    # Opening scene only on a fresh campaign
    if is_new:
        try:
            dm.opening_scene(state, CAMPAIGN_OPENING)
        except Exception as e:
            ui.error(f"DM error: {e}")
            traceback.print_exc()
        state.save(save_path)

    # Main loop
    while True:
        ui.status_line(state.player, state.player_location)
        try:
            user_input = ui.prompt("> ").strip()
        except KeyboardInterrupt:
            print()
            state.save(save_path)
            ui.success(f"Saved to {save_path}. Farewell.")
            return

        if not user_input:
            continue

        if user_input.startswith("/"):
            if handle_command(user_input, state, save_path):
                continue
            ui.warn(f"Unknown command. Type /help for the list. Or rephrase without the slash to talk to the DM.")
            continue

        # Death check
        if state.player.hp <= 0:
            ui.warn(f"{state.player.name} is unconscious. Try resting (describe being helped, or use a healing potion if you have one) or describe a death scene.")
            # Still let the player input flow through — the DM can handle it.

        try:
            dm.take_turn(state, user_input)
        except KeyboardInterrupt:
            ui.warn("\nInterrupted mid-turn. State saved up to last completed step.")
        except Exception as e:
            ui.error(f"DM error: {e}")
            traceback.print_exc()
            ui.system("You can try again, or /quit to exit.")

        # Auto-save every turn
        try:
            state.save(save_path)
        except Exception as e:
            ui.error(f"Save failed: {e}")


if __name__ == "__main__":
    main()
