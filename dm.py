"""Bedrock-backed Dungeon Master.

Uses the Converse API with tool use. Each turn:
  1. Build a fresh system prompt with current state snapshot.
  2. Append the player's message and call Converse.
  3. If the model returns toolUse blocks, execute them, append results,
     and call Converse again. Loop until stopReason == 'end_turn'.
  4. Print any text blocks as they come in.

The Bedrock model id is configurable via BEDROCK_MODEL_ID. Default targets
the US cross-region inference profile for Claude Opus 4.5 -- update this
if your account uses a different profile or region.
"""

from __future__ import annotations

import os

import boto3
from botocore.config import Config

import ui
from state import GameState, render_state_snapshot
from tools import TOOL_SCHEMAS, dispatch
from world import WORLD_BIBLE, CAMPAIGN_TITLE


DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-opus-4-5-20250929-v1:0",
)
DEFAULT_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"


SYSTEM_PROMPT_PREFIX = f"""\
You are the Dungeon Master for a D&D-style solo campaign called
"{CAMPAIGN_TITLE}". The player is the sole hero. You voice the world
and every NPC.

# How to narrate
- Second person, present tense ("you push open the door...").
- 1-4 paragraphs per response, unless a long scene calls for more.
- Voice each NPC distinctly. Once you've established a voice, stick to it.
- Telegraph danger, give the player real choices, and never railroad.
- Keep tone consistent with the campaign bible below: high fantasy, leans
  grim with sparks of warmth and humor.

# Tool use is mandatory for state changes
You have tools to mutate the game state. NEVER claim a state change
happened in narration without calling the corresponding tool. This includes:
  - Damage/healing -> call change_hp
  - XP awards -> call award_xp
  - Buying/selling/finding gold -> call change_gold
  - Loot, gifts, purchases -> call add_item / remove_item / equip_item
  - Movement between distinct named places -> call set_location
  - Meeting an NPC, or a meaningful relationship change -> call note_npc
  - Quest given / progressed / completed / failed -> call set_quest
  - Entering or leaving combat -> call set_combat
  - Resting -> call rest
  - Acquiring or recovering from a condition -> call set_condition

You may chain multiple tools in one turn if a scene calls for it.

# Dice and DCs (D&D-lite)
- Easy DC 10, Medium DC 15, Hard DC 20, Very Hard DC 25.
- For ability checks: pass `modifier` = ability_mod (+ proficiency bonus, if
  the player is plausibly proficient). The current player's stats and
  proficiency bonus are listed in the snapshot.
- For attack rolls: 1d20 + ability_mod + proficiency vs target AC. Use
  STR for melee martial, DEX for finesse/ranged, primary spellcasting
  ability for spell attacks.
- Damage: weapon dice + ability_mod (e.g. 1d8+3). On a natural 20,
  roll damage dice twice and report a critical hit.
- Saving throws: 1d20 + ability_mod (+ proficiency only if the class is
  proficient in that save).
- Use roll_dice for ALL random outcomes. Do not invent numbers.

# Memory and continuity
- The state snapshot below is rebuilt every turn from authoritative data.
- The "RECENT JOURNAL ENTRIES" section is your long-term memory across
  many turns. Write a short journal entry whenever something meaningful
  happens (key NPC met, quest progressed, scene ended, secret learned).
  Aim for ~1 journal entry per scene, not per turn.
- The "KNOWN NPCS" section is your dossier. Update it via note_npc whenever
  a new NPC is introduced or an existing one's relationship changes.
- Stay consistent: an NPC's voice, an established fact, a promise made,
  a debt owed -- all carry over. Re-read the journal and dossier each turn.

# Combat
- When combat starts, call set_combat(in_combat=true, summary=...).
- On the player's turn, ask them their action.
- On the enemies' turn, narrate and roll. Apply damage via change_hp.
- When combat ends, call set_combat(in_combat=false), award_xp for the
  encounter, and journal the outcome.

# Pacing
- Don't over-describe. A four-paragraph response is the upper bound for
  most turns. A single tense paragraph is fine in fast scenes.
- End most responses by giving the player a clear sense of what they can
  see, hear, or do -- but don't list explicit menu options. They have
  free input.

Below is the campaign bible. Internalize it.
"""


SYSTEM_PROMPT_SUFFIX = """\

# Reminders
- Always call tools for state changes. Never just narrate them.
- The journal is your long-term memory. Use it.
- Stay in character as the world. Do not break the fourth wall.
- If the player tries something completely outside D&D-genre logic, lean
  into it briefly with grace, then redirect into the world.
"""


def build_system_prompt(state: GameState) -> str:
    return (
        SYSTEM_PROMPT_PREFIX
        + "\n\n"
        + WORLD_BIBLE
        + "\n\n"
        + render_state_snapshot(state)
        + "\n\n"
        + SYSTEM_PROMPT_SUFFIX
    )


class DungeonMaster:
    def __init__(self, model_id: str | None = None, region: str | None = None):
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.region = region or DEFAULT_REGION
        cfg = Config(read_timeout=180, connect_timeout=10, retries={"max_attempts": 3})
        self.client = boto3.client("bedrock-runtime", region_name=self.region, config=cfg)

    def take_turn(self, state: GameState, user_text: str) -> None:
        """Run one player turn end-to-end, including any DM tool loops."""
        state.turn += 1
        state.messages.append({"role": "user", "content": [{"text": user_text}]})

        max_iters = 12  # safety net against tool loops
        for _ in range(max_iters):
            response = self.client.converse(
                modelId=self.model_id,
                messages=state.messages,
                system=[{"text": build_system_prompt(state)}],
                toolConfig={"tools": TOOL_SCHEMAS},
                inferenceConfig={"maxTokens": 4096, "temperature": 0.85},
            )
            msg = response["output"]["message"]
            state.messages.append(msg)

            # Print any narration text
            for block in msg["content"]:
                if "text" in block and block["text"].strip():
                    ui.dm(block["text"])

            stop_reason = response.get("stopReason")
            if stop_reason != "tool_use":
                break

            # Execute tool calls and feed results back
            tool_results = []
            for block in msg["content"]:
                if "toolUse" not in block:
                    continue
                tu = block["toolUse"]
                result_text, ok = dispatch(state, tu["name"], tu.get("input", {}))
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"text": result_text}],
                        "status": "success" if ok else "error",
                    }
                })
            state.messages.append({"role": "user", "content": tool_results})
        else:
            ui.warn("DM stopped after hitting the tool-use safety limit. Continuing.")

    def opening_scene(self, state: GameState, opening_text: str) -> None:
        """Kick off the campaign. We seed the conversation with the hardcoded
        opening, then ask the model to take it from there as DM."""
        # Print the hardcoded scene so the player sees a consistent start.
        ui.dm(opening_text)
        # Tell the DM to pick up from there. The model will likely write a
        # follow-up sentence and prompt for action -- and importantly, it'll
        # see the full state snapshot and world bible.
        seed = (
            "[GAME START]\n\n"
            "The opening scene above has just been narrated to the player. "
            "Take it from here as DM: voice the inn briefly (sights, sounds, "
            "anyone present), then prompt the player for what they do. "
            "Call note_npc for any NPC you introduce. Keep it tight -- 2 "
            "short paragraphs."
        )
        self.take_turn(state, seed)
