"""Tiny terminal UI helpers. ANSI colors, status line, banners."""

import os
import shutil
import sys
import textwrap

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GREY = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_CYAN = "\033[96m"


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"{code}{text}{C.RESET}"


def width() -> int:
    try:
        return min(shutil.get_terminal_size((100, 24)).columns, 100)
    except Exception:
        return 80


def hr(char: str = "-") -> str:
    return char * width()


def banner(title: str, subtitle: str = "") -> None:
    w = width()
    bar = "=" * w
    print(_c(C.BRIGHT_CYAN, bar))
    print(_c(C.BRIGHT_CYAN + C.BOLD, title.center(w)))
    if subtitle:
        print(_c(C.CYAN, subtitle.center(w)))
    print(_c(C.BRIGHT_CYAN, bar))


def section(title: str) -> None:
    print()
    print(_c(C.BOLD + C.CYAN, f"-- {title} " + "-" * max(0, width() - len(title) - 4)))


def dm(text: str) -> None:
    """Print DM narration with subtle wrapping and color."""
    print()
    for paragraph in text.strip().split("\n\n"):
        wrapped = textwrap.fill(
            paragraph.strip(),
            width=width(),
            replace_whitespace=False,
            drop_whitespace=True,
        )
        print(_c(C.WHITE, wrapped))
        print()


def system(text: str) -> None:
    print(_c(C.DIM + C.GREY, text))


def warn(text: str) -> None:
    print(_c(C.YELLOW, text))


def error(text: str) -> None:
    print(_c(C.BRIGHT_RED, text))


def success(text: str) -> None:
    print(_c(C.BRIGHT_GREEN, text))


def event(label: str, text: str) -> None:
    """In-game event line, e.g. dice roll or HP change."""
    print(_c(C.MAGENTA + C.BOLD, f"  [{label}] ") + _c(C.MAGENTA, text))


def roll(label: str, total: int, detail: str, dc: int | None = None) -> None:
    color = C.GREEN
    suffix = ""
    if dc is not None:
        if total >= dc:
            suffix = _c(C.BRIGHT_GREEN, f"  SUCCESS (DC {dc})")
        else:
            color = C.YELLOW
            suffix = _c(C.YELLOW, f"  FAIL (DC {dc})")
    print(_c(C.MAGENTA, f"  >>") + _c(C.BOLD + color, f" {label}: ") + _c(color, f"{detail} = {total}") + suffix)


def status_line(player, location: str) -> None:
    bar_w = 14
    hp_ratio = max(0.0, min(1.0, player.hp / max(1, player.max_hp)))
    filled = int(round(bar_w * hp_ratio))
    bar = "#" * filled + "." * (bar_w - filled)
    if hp_ratio > 0.6:
        bar_c = C.BRIGHT_GREEN
    elif hp_ratio > 0.3:
        bar_c = C.YELLOW
    else:
        bar_c = C.BRIGHT_RED
    line = (
        _c(C.BOLD, f"{player.name} ")
        + _c(C.GREY, f"({player.race} {player.char_class} L{player.level})")
        + _c(C.GREY, "  HP ")
        + _c(bar_c, f"[{bar}] {player.hp}/{player.max_hp}")
        + _c(C.GREY, f"  AC {player.ac}  XP {player.xp}  GP {player.gold}")
        + _c(C.CYAN, f"  @ {location}")
    )
    print()
    print(line)


def prompt(prefix: str = "> ") -> str:
    try:
        return input(_c(C.BRIGHT_CYAN + C.BOLD, prefix))
    except EOFError:
        return "/quit"
