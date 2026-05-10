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

import art
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
  /recap       reprint the most recent DM narration
  /save        save now (also auto-saves every turn)
  /quit        save and exit

Anything else is sent to the Dungeon Master. Be specific. The DM
voices the world; you voice your character. You can speak in
quotes, describe actions, ask questions, etc.
"""


def _last_dm_narration(state: GameState) -> str | None:
    """Return the most recent assistant text content, if any."""
    for msg in reversed(state.messages):
        if msg.get("role") != "assistant":
            continue
        texts = [b["text"] for b in msg.get("content", []) if "text" in b and b["text"].strip()]
        if texts:
            return "\n\n".join(texts)
    return None


def _print_inventory(state: GameState) -> None:
    p = state.player
    eq_lines: list[str] = []
    if not p.equipped:
        eq_lines.append("(none)")
    else:
        for slot, name in p.equipped.items():
            eq_lines.append(f"{slot:<10} {name}")
    ui.boxed("Equipped", eq_lines)

    inv_lines: list[str] = []
    if not p.inventory:
        inv_lines.append("(empty)")
    else:
        for it in p.inventory:
            qty = f" x{it['quantity']}" if it.get("quantity", 1) > 1 else ""
            inv_lines.append(f"• {it['name']}{qty}")
            desc = it.get("description", "")
            if desc:
                inv_lines.append(f"    {desc}")
    ui.boxed("Inventory", inv_lines)


def _print_journal(state: GameState, n: int = 25) -> None:
    if not state.journal:
        ui.boxed("Journal", ["(no entries yet)"])
        return
    lines = [f"turn {e['turn']:>3}: {e['text']}" for e in state.journal[-n:]]
    ui.boxed("Journal", lines)


def _print_quests(state: GameState) -> None:
    if not state.quests:
        ui.boxed("Quests", ["(no quests yet)"])
        return
    lines: list[str] = []
    for name, q in state.quests.items():
        status = q.get("status", "active")
        lines.append(f"• {name}  [{status}]")
        if q.get("description"):
            lines.append(f"    {q['description']}")
        if q.get("reward"):
            lines.append(f"    reward: {q['reward']}")
    ui.boxed("Quests", lines)


def _print_map(state: GameState) -> None:
    discovered = [(n, l) for n, l in state.locations.items() if l.get("discovered")]
    rumored = [(n, l) for n, l in state.locations.items() if not l.get("discovered")]
    lines: list[str] = []
    lines.append("DISCOVERED")
    if not discovered:
        lines.append("    (none)")
    for n, l in discovered:
        marker = "✦" if n == state.player_location else "•"
        lines.append(f"  {marker} {n}  ({l.get('type', '?')}, {l.get('region', '?')})")
        if l.get("description"):
            lines.append(f"      {l['description']}")
    if rumored:
        lines.append("")
        lines.append("RUMORED")
        for n, l in rumored:
            lines.append(f"  ◌ {n}  ({l.get('region', '?')})")
            if l.get("description"):
                lines.append(f"      {l['description']}")
    ui.boxed("World Map", lines)


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
    elif cmd in ("/recap", "/last"):
        last = _last_dm_narration(state)
        if last:
            ui.dm(last)
        else:
            ui.system("(no narration to recap yet)")
    elif cmd == "/save":
        try:
            state.save(save_path)
            ui.success(f"Saved to {save_path}.")
        except Exception as e:
            ui.error(f"Save failed: {e}")
    elif cmd in ("/quit", "/exit", "/q!"):
        try:
            state.save(save_path)
            ui.success(f"Saved to {save_path}. Farewell.")
        except Exception as e:
            ui.error(f"Save failed: {e}. Quitting anyway.")
        sys.exit(0)
    else:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{CAMPAIGN_TITLE} -- a CLI D&D game with an LLM DM.")
    parser.add_argument("--new", action="store_true", help="Start a new campaign (overwrites save).")
    parser.add_argument("--save", default="save.json", help="Path to save file (default: save.json).")
    parser.add_argument("--region", default=None, help="AWS region (default: env or us-east-1).")
    parser.add_argument("--model", default=None, help="Bedrock model id (default: env or Claude Opus 4.5 US inference profile).")
    parser.add_argument("--profile", default=None, help="AWS profile name (default: env AWS_PROFILE, e.g. 'lytix').")
    args = parser.parse_args()

    save_path = Path(args.save)

    ui.title_screen(art.TITLE_ART, art.CAMPAIGN_BANNER)

    # Load or create
    state: GameState
    is_new = False
    if save_path.exists() and not args.new:
        # Try to peek at the save so the prompt can describe what's in it.
        # If the peek fails, fall through to the normal load-and-fail path.
        peek: GameState | None = None
        try:
            peek = GameState.load(save_path)
        except Exception as e:
            ui.warn(f"Save file at {save_path} could not be read ({e}).")

        if peek is not None:
            p = peek.player
            ui.section("Existing save found")
            print(f"  file:      {save_path}")
            print(f"  character: {p.name} -- level {p.level} {p.race} {p.char_class}")
            print(f"  hp:        {p.hp}/{p.max_hp}    gold: {p.gold}    xp: {p.xp}")
            print(f"  location:  {peek.player_location}")
            print(f"  turn:      {peek.turn}")
            if peek.quests:
                active = [n for n, q in peek.quests.items() if q.get("status", "active") == "active"]
                if active:
                    print(f"  quests:    {', '.join(active)}")
            choice = ui.prompt("[c]ontinue this campaign or start [n]ew? (continue) ").strip().lower()
        else:
            choice = ui.prompt(f"Save file found at {save_path}. [c]ontinue or [n]ew? ").strip().lower()

        if choice in ("n", "new"):
            if ui.prompt(f"Starting new will overwrite {save_path}. Are you sure? [y/N] ").strip().lower() != "y":
                ui.system("Aborted.")
                sys.exit(0)
            is_new = True
        else:
            try:
                state = peek if peek is not None else GameState.load(save_path)
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
        dm = DungeonMaster(model_id=args.model, region=args.region, profile=args.profile)
    except Exception as e:
        ui.error(f"Failed to initialize Bedrock client: {e}")
        ui.system("Make sure your AWS credentials are configured and the model id is correct.")
        sys.exit(1)

    profile_str = f"  profile: {dm.profile}" if dm.profile else ""
    ui.system(f"DM model: {dm.model_id}  region: {dm.region}{profile_str}")

    # Opening scene only on a fresh campaign
    if is_new:
        try:
            dm.opening_scene(state, CAMPAIGN_OPENING)
        except Exception as e:
            ui.error(f"DM error: {e}")
            traceback.print_exc()
        state.save(save_path)
    else:
        # On resume, replay the last DM narration so the player has context.
        last = _last_dm_narration(state)
        if last:
            ui.section("Where you left off")
            ui.dm(last)
        else:
            ui.system("(no prior narration found; just describe what you do)")

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
