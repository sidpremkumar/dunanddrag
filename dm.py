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

import json
import os

import boto3
from botocore.config import Config

import ui
from state import GameState, render_state_snapshot
from tools import TOOL_SCHEMAS, dispatch
from world import WORLD_BIBLE, CAMPAIGN_TITLE


# The bare `anthropic.claude-opus-4-5-...` ID rejects on-demand calls --
# Bedrock requires the `us.` (or other regional) inference-profile prefix.
DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
)
DEFAULT_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
DEFAULT_PROFILE = os.environ.get("AWS_PROFILE")


SYSTEM_PROMPT_PREFIX = f"""\
You are the Dungeon Master for a D&D-style solo campaign called
"{CAMPAIGN_TITLE}". The player is the sole hero. You voice the world
and every NPC.

# How to narrate -- BE TERSE
- Second person, present tense ("you push open the door").
- DEFAULT to 2-5 short sentences per response. One paragraph max.
  Only go longer (still capped at 2 short paragraphs) for genuine set
  pieces -- a new location, a boss reveal, the end of a major scene.
- Plain words over fancy ones. "smell" not "miasma", "old" not "ancient",
  "dark" not "stygian". No purple prose. No piled-up adjectives.
- Cut filler: "the air carries the faint reek of...", "you feel a sense
  of...", "as you step forward..." -- delete these. State the thing.
- Show, don't decorate. One concrete sensory detail beats three vague
  evocative ones. Pick the sharpest one and stop.
- NPC dialogue: short. Real people speak in fragments and interruptions,
  not monologues. 1-2 lines per turn unless a speech is the point.
- Voice each NPC distinctly, then stick to it.
- End most turns with a clear hook -- what they see, hear, or are asked.
  Don't list options. Don't ask "what do you do?" every turn; the prompt
  is implied.
- Telegraph danger, give real choices, never railroad.

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
  - Resting -> call rest (long rest auto-restores spell slots and ticks +1 day)
  - Casting a leveled spell (cantrips don't count) -> call change_spell_slots
    with delta=-1 at the slot level used. Wizards/Clerics ONLY -- the
    snapshot shows current slots when applicable.
  - Travel / downtime that passes a day or more -> call advance_time
  - Acquiring or recovering from a condition -> call set_condition
  - Gaining a pet/animal/hireling -> call add_companion
  - A companion taking damage, healing, growing closer or more wary,
    being sent home or recalled -> call update_companion
  - A companion dying or leaving for good -> call remove_companion
  - Giving a companion food, treats, gifts, or trinkets from inventory ->
    call give_companion_item (this also shifts friendliness)

You may chain multiple tools in one turn if a scene calls for it.

# Atmosphere: ASCII art -- USE IT OFTEN
You have a `show_art` tool that renders a framed ASCII picture. The
player has explicitly asked for more art. Lean in. Aim for roughly one
piece of art every 2-4 turns when there's something concrete to draw.
Skip art only when nothing visual changed (e.g. pure dialogue continuation).

Strong reasons to draw:
  - Arriving anywhere new -- village, road, forest, ruin, room (silhouette,
    layout, gate, doorway).
  - Meeting an NPC for the first time (small portrait or sigil).
  - Combat openings -- show the foe(s), the terrain, or both.
  - Loot: weapons, armor, scrolls, magic items -- sketch them.
  - Reveals: a map, a symbol, a creature in the dark, a dragon's eye.
  - Travel montages: the road, a campfire, a passing landmark.
  - Mood beats: rain over a graveyard, a still pond, a closed door.

Constraints:
  - Printable ASCII / common box-drawing chars only. NO color codes.
  - Max ~70 columns wide, ~12 rows tall. The frame is added for you.
  - Hand-draw inline. Make it RECOGNIZABLE -- a tree, a sword, a face,
    a building -- not abstract scribbles. Stick figures and silhouettes
    are fine; aim for clarity over detail.
  - One art block per turn (you can call show_art at most once).
  - Pair the art with a SHORT caption (5-10 words) and ~1-2 sentences
    of narration -- the picture carries weight, the prose doesn't have
    to repeat what it shows.

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

# Out-of-character exchanges
The conversation history may contain user messages tagged
`[OUT-OF-CHARACTER QUESTION ...]` and assistant replies prefixed `[OOC]`.
These are meta player-to-DM exchanges -- guidance, clarifications,
"can I do X in this game?" -- NOT in-character actions. They did not
happen in the world. NPCs did not hear them. Time did not pass. Do not
journal them, do not let NPCs react to them, do not double back on
information revealed in them as if it were freshly learned in-fiction.

# Companions (pets, animals, hirelings)
The player can have multiple companions in their party at once. Each has
HP/AC/attack stats and a friendliness score 0-100 with named tiers:
  wary (<20) - neutral (<40) - friendly (<60) - bonded (<80) - devoted (>=80)
Friendliness shifts based on treatment:
  - Petting / kind words / praise: +3 to +5
  - Feeding a treat or sharing rations: +5 to +10
  - Giving a thoughtful or prized gift: +10 to +20 (use give_companion_item)
  - Saving them in combat or from harm: +10 to +25
  - Ignoring them for a long stretch: -2
  - Putting them in danger casually: -5 to -10
  - Striking, starving, or betraying them: -20 to -50
A devoted companion fights to the death for the player. A wary one may
flee, refuse commands, or wander off. Roleplay this honestly.

In combat, companions act on the player's initiative. Roll their attacks
with their stored attack_bonus and damage_dice. They take damage like
any creature -- call update_companion(hp_delta=-N) when hit. HP 0 means
downed (not dead unless DM declares so or remove_companion is called).
Resting (short or long) heals in-party companions automatically; you do
not need a separate tool call for that.

Show the player's companions in opening scenes and big moments -- they
are part of the party. A `show_art` block of a new companion when first
gained is a great fit.

# Memory and continuity
- The state snapshot below is rebuilt every turn from authoritative data.
- Older message history rolls off the context window after ~15 turns;
  ONLY journal entries persist beyond that. Under-journaling means
  permanent memory loss for the campaign. Treat the journal tool as
  obligatory, not optional.
- You MUST write a short journal entry (1-2 sentences, via the `journal`
  tool) when ANY of these occur on a turn:
    * The player enters a NAMED place for the first time (or returns
      after long absence)
    * The player meets a NAMED NPC for the first time
    * An NPC's relationship to the player shifts meaningfully
    * A quest starts, hits a major beat, completes, or fails
    * The player gains, loses, or loses-the-trust-of a companion
    * The player learns a secret, a piece of lore, or a clue
    * The player acquires a notable item (magical, plot-relevant, valuable)
    * A combat encounter ends -- record the outcome briefly
    * A scene ends, a day passes, or significant time is skipped
  Write as if your future self has amnesia about everything except the
  bullets you record. One entry per scene is the floor; never per-turn
  spam, never zero-when-something-real-happened.
- The "KNOWN NPCS" section is your dossier. Update it via note_npc whenever
  a new NPC is introduced or an existing one's relationship changes.
- Stay consistent: an NPC's voice, an established fact, a promise made,
  a debt owed -- all carry over. Re-read the journal and dossier each turn.

# Combat
- When combat starts, call set_combat(in_combat=true, summary=...).
- On the player's turn, ask them their action.
- Companions act on the SAME initiative as the player. Each round, after
  the player acts, take a turn for every in-party companion with HP > 0:
    1. Pick a sensible target (usually whoever is threatening the player).
    2. Roll the attack: roll_dice('1d20', modifier=<companion.attack_bonus>,
       reason='<Companion> bites the goblin', dc=<enemy AC>).
    3. On hit, roll damage with the companion's stored damage_dice (e.g.
       '1d6+1') and apply it. Enemies' HP isn't tracked in state -- you
       narrate it -- but you MUST call update_companion(hp_delta=-N) when
       the companion takes damage and change_hp(amount=-N) for the player.
    4. Lower-friendliness companions are less reliable: a 'wary' pet may
       refuse the order, fight at half-effort, or break and flee on its
       turn. A 'devoted' one fights to the death and may even take a hit
       meant for the player.
- A companion at HP 0 is DOWNED, not dead. They can't take actions and
  drop where they fell. Reviving mid-combat is possible: a healing
  potion, a Cleric's Healing Word, etc. -- just call update_companion
  (hp_delta=+N). They die only if you call remove_companion.
- On the enemies' turn, narrate and roll. Apply damage via change_hp
  (player) and update_companion (companions) -- enemies may target
  either, especially the smaller/weaker ones first.
- When combat ends, call set_combat(in_combat=false), award_xp for the
  encounter, and journal the outcome. If a companion was bloodied or
  downed but survived, +5 to +10 friendliness for shared danger is
  appropriate -- call update_companion.

# Pacing
- Brevity beats description. 2-5 sentences is the norm, not the floor.
- One tight paragraph beats two flowery ones. Cut.
- Free input -- don't list menu options.

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
    def __init__(self, model_id: str | None = None, region: str | None = None, profile: str | None = None):
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.region = region or DEFAULT_REGION
        self.profile = profile or DEFAULT_PROFILE
        cfg = Config(read_timeout=180, connect_timeout=10, retries={"max_attempts": 3})
        session = boto3.Session(profile_name=self.profile) if self.profile else boto3.Session()
        self.client = session.client("bedrock-runtime", region_name=self.region, config=cfg)

    def _converse_stream(self, state: GameState, with_tools: bool = True, system_suffix: str = ""):
        """Single Bedrock ConverseStream call. Returns the boto3 response.
        The caller is responsible for consuming `response['stream']`.

        Note: `toolConfig` is ALWAYS sent. Bedrock rejects requests whose
        message history contains toolUse/toolResult blocks but no toolConfig
        -- and any non-trivial turn's history will. The `with_tools` flag
        is preserved for callers but is effectively just a hint; tool
        suppression is done via the system prompt override, and any rogue
        toolUse blocks the model emits are stripped by the caller."""
        kwargs = dict(
            modelId=self.model_id,
            messages=state.messages,
            system=[{"text": build_system_prompt(state) + system_suffix}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.85},
            toolConfig={"tools": TOOL_SCHEMAS},
        )
        return self.client.converse_stream(**kwargs)

    def _consume_stream(self, response) -> tuple[dict, str | None]:
        """Walk a streaming Converse response, printing text deltas live.

        Returns the assembled assistant message (Bedrock Converse format)
        and the final stopReason.
        """
        # Map from contentBlockIndex -> in-progress block dict. For text
        # blocks we accumulate the printed text. For tool_use blocks we
        # accumulate the JSON-string input fragments and parse at stop.
        blocks: dict[int, dict] = {}
        order: list[int] = []  # preserve content-block order for the final list
        stop_reason: str | None = None
        text_stream = ui.DMStream()

        for event in response["stream"]:
            if "messageStart" in event:
                continue
            if "contentBlockStart" in event:
                idx = event["contentBlockStart"]["contentBlockIndex"]
                start = event["contentBlockStart"].get("start") or {}
                if "toolUse" in start:
                    tu = start["toolUse"]
                    blocks[idx] = {
                        "kind": "toolUse",
                        "toolUseId": tu["toolUseId"],
                        "name": tu["name"],
                        "input_str": "",
                    }
                if idx not in order:
                    order.append(idx)
                continue
            if "contentBlockDelta" in event:
                idx = event["contentBlockDelta"]["contentBlockIndex"]
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    if idx not in blocks:
                        blocks[idx] = {"kind": "text", "text": ""}
                        if idx not in order:
                            order.append(idx)
                    blocks[idx]["text"] += delta["text"]
                    text_stream.write(delta["text"])
                elif "toolUse" in delta:
                    if idx in blocks and blocks[idx].get("kind") == "toolUse":
                        blocks[idx]["input_str"] += delta["toolUse"].get("input", "")
                continue
            if "contentBlockStop" in event:
                continue
            if "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason")
                continue
            # metadata, throttling, etc. — ignore.

        text_stream.end()

        # Assemble final message in Bedrock Converse format.
        content: list[dict] = []
        for idx in order:
            block = blocks.get(idx)
            if not block:
                continue
            if block["kind"] == "text":
                content.append({"text": block["text"]})
            elif block["kind"] == "toolUse":
                raw = block.get("input_str", "").strip()
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {}
                content.append({"toolUse": {
                    "toolUseId": block["toolUseId"],
                    "name": block["name"],
                    "input": parsed,
                }})
        return {"role": "assistant", "content": content}, stop_reason

    @staticmethod
    def _strip_tool_use(msg: dict) -> dict:
        """Drop toolUse content blocks from an assistant message. Used after
        no-tools calls (/ask, iteration-cap fallback) where we told the model
        not to call tools. If it disobeys, an unpaired toolUse block in the
        saved history would cause Bedrock to reject the NEXT turn."""
        content = [b for b in msg.get("content", []) if "toolUse" not in b]
        if not content:
            content = [{"text": ""}]
        return {"role": msg.get("role", "assistant"), "content": content}

    def take_turn(self, state: GameState, user_text: str) -> None:
        """Run one player turn end-to-end, including any DM tool loops.

        On any error during the model call, rolls back any messages added
        in this turn so the saved history stays in clean alternation and
        resume keeps working.
        """
        baseline_len = len(state.messages)
        state.turn += 1
        state.messages.append({"role": "user", "content": [{"text": user_text}]})

        # Safety net against runaway tool loops. Each iteration is one
        # Bedrock Converse call; the model can chain many tool_use blocks
        # in a single message. A combat round with the player + multiple
        # companions can legitimately take 3-5 iterations (attack roll,
        # damage roll, hp updates, then enemy responses), so 16 gives
        # ~3 rounds of headroom before the forced-close kicks in.
        max_iters = 16
        try:
            for _ in range(max_iters):
                response = self._converse_stream(state)
                msg, stop_reason = self._consume_stream(response)
                state.messages.append(msg)

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
                # Hit the iteration cap. History ends with a `user` message of
                # toolResult blocks, so we MUST send one more call to get a
                # final assistant text -- otherwise the next take_turn appends
                # a `user` after `user` and Bedrock rejects. Send with
                # toolConfig (required: history has tool blocks) but instruct
                # the model NOT to call any more tools, and strip any rogue
                # toolUse it emits anyway so the next turn validates.
                ui.warn("DM hit the tool-use safety cap. Forcing a closing narration.")
                response = self._converse_stream(
                    state,
                    with_tools=False,
                    system_suffix=(
                        "\n\n# OVERRIDE\nYou have used your tool budget for this turn. "
                        "Do NOT call any more tools. Write a brief closing "
                        "narration (1-2 paragraphs) that wraps the scene, and stop."
                    ),
                )
                msg, _ = self._consume_stream(response)
                state.messages.append(self._strip_tool_use(msg))
        except Exception:
            # Roll back anything we added this turn so resume works cleanly.
            del state.messages[baseline_len:]
            state.turn -= 1
            raise

    def ask_meta(self, state: GameState, question: str) -> None:
        """Out-of-character question to the DM. No state changes, no time
        advancement, no scene progress. The DM answers briefly as a guide.

        The exchange IS persisted in the message history (so future turns
        can reference it), but `state.turn` is NOT incremented and no tools
        are available, so no game state can mutate.
        """
        baseline_len = len(state.messages)
        framed = (
            "[OUT-OF-CHARACTER QUESTION -- not an in-game action]\n"
            f"{question.strip()}"
        )
        state.messages.append({"role": "user", "content": [{"text": framed}]})
        meta_override = (
            "\n\n# OOC META MODE\n"
            "The player just asked an out-of-character question (player-to-DM, "
            "not in-character speech). Answer them directly as the DM/guide.\n"
            "- 1-3 short sentences. No flowery language.\n"
            "- DO NOT advance the scene, DO NOT have NPCs react, DO NOT pass time.\n"
            "- DO NOT call ANY tools this turn -- no roll_dice, no note_npc,\n"
            "  no show_art, nothing. This is a pure text reply.\n"
            "- Plainly say if something is not possible in this campaign / world. "
            "  When you can, point at the closest in-world option (a person, a "
            "  place, a quest hook) without committing the player to it.\n"
            "- It is fine to break the fourth wall here. Prefix your reply with "
            "  '[OOC]' so the player knows it is meta.\n"
            "- Do NOT write a journal entry for this exchange."
        )
        try:
            response = self._converse_stream(state, with_tools=False, system_suffix=meta_override)
            msg, _ = self._consume_stream(response)
            # Strip any rogue toolUse: if the model defied the instruction,
            # an unpaired toolUse would wedge the next take_turn.
            state.messages.append(self._strip_tool_use(msg))
        except Exception:
            del state.messages[baseline_len:]
            raise

    def opening_scene(self, state: GameState, opening_text: str) -> None:
        """Kick off the campaign by handing the DM the hardcoded opening
        as a system-style seed message. The DM picks up from there."""
        # Print the hardcoded scene so the player sees a consistent start.
        ui.dm(opening_text)
        # Embed the opening text so the DM knows EXACTLY what was just shown
        # to the player, and can follow up consistently.
        seed = (
            "[GAME START]\n\n"
            "The opening above was just shown to the player. Continue as DM. "
            "Step inside the Stag & Saddle: 3-5 short sentences total. Pick ONE "
            "concrete sight, ONE sound, and name 1-2 people present. Strongly "
            "consider a show_art block of the inn's interior or a patron. Call "
            "note_npc for anyone you introduce. End on a hook, not a question.\n\n"
            "----- OPENING SCENE -----\n"
            f"{opening_text.strip()}\n"
            "----- END OPENING SCENE -----"
        )
        self.take_turn(state, seed)
