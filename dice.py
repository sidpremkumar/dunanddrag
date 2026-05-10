"""Dice notation parser and roller. Supports things like '1d20', '2d6+3', 'd8'."""

import random
import re

_DICE_RE = re.compile(r"^\s*(\d+)?\s*[dD]\s*(\d+)\s*([+-]\s*\d+)?\s*$")


def roll(notation: str, extra_modifier: int = 0) -> dict:
    """Roll dice in standard notation.

    Returns a dict with: notation, rolls (list[int]), modifier, total, detail.
    """
    m = _DICE_RE.match(notation)
    if not m:
        raise ValueError(f"Bad dice notation: {notation!r}")
    count = int(m.group(1) or 1)
    sides = int(m.group(2))
    mod_str = (m.group(3) or "").replace(" ", "")
    mod = int(mod_str) if mod_str else 0
    mod += extra_modifier
    if count < 1 or count > 100 or sides < 2 or sides > 1000:
        raise ValueError(f"Unreasonable dice: {notation!r}")
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + mod

    detail = f"[{', '.join(str(r) for r in rolls)}]"
    if mod:
        detail += f" {'+' if mod >= 0 else ''}{mod}"
    return {
        "notation": notation,
        "rolls": rolls,
        "modifier": mod,
        "total": total,
        "detail": detail,
    }


def d20_check(modifier: int = 0) -> dict:
    raw = random.randint(1, 20)
    return {
        "notation": "1d20",
        "rolls": [raw],
        "modifier": modifier,
        "total": raw + modifier,
        "raw": raw,
        "is_crit": raw == 20,
        "is_fumble": raw == 1,
        "detail": f"[{raw}]" + (f" {'+' if modifier >= 0 else ''}{modifier}" if modifier else ""),
    }


def roll_4d6_drop_lowest() -> int:
    rolls = sorted(random.randint(1, 6) for _ in range(4))
    return sum(rolls[1:])
