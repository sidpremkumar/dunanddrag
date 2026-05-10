"""Terminal UI helpers: colors, boxes, banners, status line, art rendering.

Behavior summary:
  - banner(title, subtitle): big bordered title block.
  - section(title): a thin labeled rule.
  - boxed(title, lines): a full bordered box for inventory / journal / etc.
  - dm(text): word-wrapped DM narration with a subtle left vertical bar.
  - art_block(art, caption): render ASCII art verbatim inside a frame.
  - status_line(player, location): one-line HUD with HP bar and stats.
  - event(label, text), roll(...): colored in-game event lines.
  - prompt(prefix): readline prompt with color hint.

NO_COLOR=1 disables color escapes and switches to plain ASCII frames.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap

# Importing readline (when available) transparently upgrades the built-in
# input() to support backspace, arrow keys, line history, and editing.
# We don't use the module directly -- the import alone hooks it in.
try:
    import readline  # noqa: F401
except ImportError:
    pass  # not available on some platforms (e.g. vanilla Windows)

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_USE_UNICODE = os.environ.get("ASCII_ONLY") is None


# --- Colors ---------------------------------------------------------------


class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    ITALIC = "\033[3m"
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
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"{code}{text}{C.RESET}"


# --- Box-drawing characters ----------------------------------------------


class B:
    """Box-drawing chars. Falls back to ASCII when ASCII_ONLY is set."""

    if _USE_UNICODE:
        H = "─"
        V = "│"
        TL = "╭"
        TR = "╮"
        BL = "╰"
        BR = "╯"
        TEE_L = "├"
        TEE_R = "┤"
        BOLD_H = "═"
        BOLD_V = "║"
        BOLD_TL = "╔"
        BOLD_TR = "╗"
        BOLD_BL = "╚"
        BOLD_BR = "╝"
        BAR_FULL = "█"
        BAR_EMPTY = "░"
        BULLET = "•"
        ARROW = "→"
    else:
        H = "-"
        V = "|"
        TL = "+"
        TR = "+"
        BL = "+"
        BR = "+"
        TEE_L = "+"
        TEE_R = "+"
        BOLD_H = "="
        BOLD_V = "|"
        BOLD_TL = "+"
        BOLD_TR = "+"
        BOLD_BL = "+"
        BOLD_BR = "+"
        BAR_FULL = "#"
        BAR_EMPTY = "."
        BULLET = "*"
        ARROW = "->"


# --- Width / layout ------------------------------------------------------


_MIN_WIDTH = 60
_MAX_WIDTH = 100


def width() -> int:
    try:
        cols = shutil.get_terminal_size((100, 24)).columns
    except Exception:
        cols = 80
    return max(_MIN_WIDTH, min(_MAX_WIDTH, cols))


def hr(char: str = "-") -> str:
    return char * width()


# --- Banner / sections ---------------------------------------------------


def banner(title: str, subtitle: str = "") -> None:
    w = width()
    inner = w - 4  # for the two-char border on each side
    bar_top = B.BOLD_TL + B.BOLD_H * (w - 2) + B.BOLD_TR
    bar_bot = B.BOLD_BL + B.BOLD_H * (w - 2) + B.BOLD_BR
    blank = B.BOLD_V + " " * (w - 2) + B.BOLD_V

    print()
    print(_c(C.BRIGHT_RED + C.BOLD, bar_top))
    print(_c(C.BRIGHT_RED, blank))
    title_line = title.center(inner)
    print(_c(C.BRIGHT_RED, B.BOLD_V + " ") + _c(C.BRIGHT_YELLOW + C.BOLD, title_line) + _c(C.BRIGHT_RED, " " + B.BOLD_V))
    if subtitle:
        sub_line = subtitle.center(inner)
        print(_c(C.BRIGHT_RED, B.BOLD_V + " ") + _c(C.YELLOW, sub_line) + _c(C.BRIGHT_RED, " " + B.BOLD_V))
    print(_c(C.BRIGHT_RED, blank))
    print(_c(C.BRIGHT_RED + C.BOLD, bar_bot))
    print()


def title_screen(art: str, banner_block: str) -> None:
    """Print the multi-line title art followed by the banner block.

    Both args are raw multi-line strings (e.g. from art.py).
    """
    print()
    for line in art.rstrip("\n").split("\n"):
        print(_c(C.BRIGHT_RED, line))
    for line in banner_block.rstrip("\n").split("\n"):
        print(_c(C.BRIGHT_YELLOW + C.BOLD, line))
    print()


def section(title: str) -> None:
    """A thin labeled rule used between groups. Quieter than `banner`."""
    w = width()
    label = f" {title} "
    rule = B.H * max(0, w - len(label) - 4)
    print()
    print(
        _c(C.CYAN + C.BOLD, B.TEE_L + B.H + B.H)
        + _c(C.BRIGHT_CYAN + C.BOLD, label)
        + _c(C.CYAN + C.BOLD, rule + B.TEE_R)
    )


def boxed(title: str, lines: list[str], color: str = C.CYAN) -> None:
    """Render a list of plain lines inside a titled box. Wraps long lines."""
    w = width()
    inner = w - 4  # space for `│ ` and ` │`
    title_label = f" {title} "
    top = B.TL + B.H + title_label + B.H * max(0, w - 4 - len(title_label)) + B.TR
    bot = B.BL + B.H * (w - 2) + B.BR
    print()
    print(_c(color + C.BOLD, top))
    for raw in lines:
        # Split on newlines first so the caller can produce blank rows.
        for sub in raw.split("\n"):
            if not sub:
                print(_c(color, B.V) + " " * (w - 2) + _c(color, B.V))
                continue
            # Wrap to inner width.
            wrapped = textwrap.wrap(sub, width=inner) or [""]
            for piece in wrapped:
                pad = inner - _visible_len(piece)
                print(
                    _c(color, B.V) + " "
                    + piece + " " * pad
                    + " " + _c(color, B.V)
                )
    print(_c(color + C.BOLD, bot))


def art_block(art: str, caption: str = "", color: str = C.BRIGHT_MAGENTA) -> None:
    """Render verbatim ASCII art inside a soft frame. Does not word-wrap."""
    art = art.rstrip("\n").lstrip("\n")
    if not art:
        return
    w = width()
    art_lines = art.split("\n")
    art_w = max(_visible_len(l) for l in art_lines)
    box_w = min(w, art_w + 4)
    inner = box_w - 4
    top = B.TL + B.H * (box_w - 2) + B.TR
    bot = B.BL + B.H * (box_w - 2) + B.BR
    print()
    print(_c(color, top))
    for line in art_lines:
        # Truncate or pad to fit.
        visible = line if _visible_len(line) <= inner else line[:inner]
        pad = inner - _visible_len(visible)
        print(_c(color, B.V) + " " + visible + " " * pad + " " + _c(color, B.V))
    if caption:
        print(_c(color, B.V) + " " + " " * inner + " " + _c(color, B.V))
        cap_lines = textwrap.wrap(caption, width=inner) or [caption]
        for cl in cap_lines:
            pad = inner - _visible_len(cl)
            print(_c(color, B.V) + " " + _c(C.ITALIC + color, cl) + " " * pad + " " + _c(color, B.V))
    print(_c(color, bot))


# --- DM narration --------------------------------------------------------


def dm(text: str) -> None:
    """Word-wrapped DM narration, indented with a subtle left bar.

    Use this for one-shot prints (e.g. /recap, opening replays). For live
    streaming from the model, use DMStream below.
    """
    stream = DMStream()
    stream.write(text)
    stream.end()


class DMStream:
    """Streams DM narration to the terminal token-by-token.

    Buffers a partial word until a whitespace boundary so wrapping never
    splits a word in the middle. Reuses the same `│` left-bar visual as
    the static dm() renderer.
    """

    def __init__(self) -> None:
        self.col = 0
        self.indent = "  "  # space after the bar
        self.bar_visible = "│" if _USE_UNICODE else "|"
        self._started = False
        self._buf = ""  # accumulating partial word

    @property
    def _indent_width(self) -> int:
        # bar (1) + indent spaces
        return 1 + len(self.indent)

    def _bar_prefix(self) -> str:
        return _c(C.BRIGHT_MAGENTA + C.DIM, self.bar_visible) + self.indent

    def _start(self) -> None:
        if not self._started:
            sys.stdout.write("\n")
            sys.stdout.write(self._bar_prefix())
            self.col = self._indent_width
            self._started = True

    def _newline(self) -> None:
        sys.stdout.write("\n")
        sys.stdout.write(self._bar_prefix())
        self.col = self._indent_width

    def _emit_word(self, word: str) -> None:
        if not word:
            return
        target_w = width() - 2  # right margin
        sep_needed = self.col > self._indent_width
        # If the word won't fit on the current line, wrap first.
        if sep_needed and self.col + 1 + len(word) > target_w:
            self._newline()
            sep_needed = False
        elif not sep_needed and len(word) > target_w - self._indent_width:
            # Single word longer than the line. Just write it; terminal will
            # hard-wrap. Avoid infinite loop.
            pass
        if sep_needed:
            sys.stdout.write(" ")
            self.col += 1
        sys.stdout.write(_c(C.BRIGHT_WHITE, word))
        self.col += len(word)

    def write(self, text: str) -> None:
        """Feed an incremental chunk of model output."""
        if not text:
            return
        self._start()
        for ch in text:
            if ch == "\n":
                if self._buf:
                    self._emit_word(self._buf)
                    self._buf = ""
                self._newline()
            elif ch == " " or ch == "\t":
                if self._buf:
                    self._emit_word(self._buf)
                    self._buf = ""
                # Spacing between words is handled inside _emit_word.
            else:
                self._buf += ch
        sys.stdout.flush()

    def end(self) -> None:
        """Flush the trailing partial word and finish the block."""
        if self._buf:
            self._emit_word(self._buf)
            self._buf = ""
        if self._started:
            sys.stdout.write("\n\n")
            sys.stdout.flush()
        self._started = False
        self.col = 0


# --- Status line ---------------------------------------------------------


def status_line(player, location: str) -> None:
    bar_w = 14
    hp = max(0, player.hp)
    max_hp = max(1, player.max_hp)
    ratio = hp / max_hp
    filled = max(0, min(bar_w, int(round(bar_w * ratio))))
    bar = B.BAR_FULL * filled + B.BAR_EMPTY * (bar_w - filled)

    if ratio > 0.6:
        bar_c = C.BRIGHT_GREEN
    elif ratio > 0.3:
        bar_c = C.YELLOW
    else:
        bar_c = C.BRIGHT_RED

    sep = _c(C.GREY, "  " + B.V + "  ")
    parts = [
        _c(C.BOLD + C.BRIGHT_WHITE, player.name)
        + " "
        + _c(C.GREY, f"({player.race} {player.char_class} L{player.level})"),
        _c(C.GREY, "HP ") + _c(bar_c, bar) + _c(C.WHITE, f" {hp}/{max_hp}"),
        _c(C.GREY, "AC ") + _c(C.WHITE, str(player.ac)),
        _c(C.GREY, "XP ") + _c(C.WHITE, str(player.xp)),
        _c(C.GREY, "GP ") + _c(C.YELLOW, str(player.gold)),
        _c(C.GREY, "@ ") + _c(C.BRIGHT_CYAN, location),
    ]
    print()
    print("  " + sep.join(parts))


# --- Events / rolls ------------------------------------------------------


def system(text: str) -> None:
    """Instructional / informational text. Readable cyan -- not 'dim grey'
    which renders almost invisibly on many terminals."""
    print(_c(C.BRIGHT_CYAN, text))


def hint(text: str) -> None:
    """A faint inline hint. Use sparingly -- this is the only style that's
    intentionally low-contrast (e.g. for status lines like 'DM model: ...')."""
    print(_c(C.GREY, text))


def warn(text: str) -> None:
    print(_c(C.YELLOW, text))


def error(text: str) -> None:
    print(_c(C.BRIGHT_RED, text))


def success(text: str) -> None:
    print(_c(C.BRIGHT_GREEN, text))


# Color hint per event label, so different events read at a glance.
_EVENT_COLORS: dict[str, str] = {
    "DAMAGE": C.BRIGHT_RED,
    "HEAL": C.BRIGHT_GREEN,
    "DOWN": C.BRIGHT_RED + C.BOLD,
    "XP": C.BRIGHT_CYAN,
    "LEVEL UP": C.BRIGHT_YELLOW + C.BOLD,
    "GOLD": C.YELLOW,
    "ITEM+": C.BRIGHT_GREEN,
    "ITEM-": C.GREY,
    "EQUIP": C.BRIGHT_BLUE,
    "MOVE": C.BRIGHT_CYAN,
    "DISCOVERED": C.BRIGHT_MAGENTA + C.BOLD,
    "NPC": C.BRIGHT_BLUE,
    "QUEST": C.BRIGHT_YELLOW,
    "COMBAT": C.BRIGHT_RED + C.BOLD,
    "REST": C.GREEN,
    "CONDITION": C.BRIGHT_MAGENTA,
}


def event(label: str, text: str) -> None:
    color = _EVENT_COLORS.get(label, C.BRIGHT_MAGENTA)
    print(
        "  " + _c(color, B.BULLET + " ")
        + _c(color + C.BOLD, f"[{label}]")
        + " " + _c(color, text)
    )


def roll(label: str, total: int, detail: str, dc: int | None = None) -> None:
    color = C.BRIGHT_GREEN
    suffix = ""
    if dc is not None:
        if total >= dc:
            suffix = "  " + _c(C.BRIGHT_GREEN + C.BOLD, f"✓ SUCCESS (DC {dc})") if _USE_UNICODE else "  " + _c(C.BRIGHT_GREEN + C.BOLD, f"SUCCESS (DC {dc})")
        else:
            color = C.YELLOW
            suffix = "  " + _c(C.YELLOW + C.BOLD, f"✗ FAIL (DC {dc})") if _USE_UNICODE else "  " + _c(C.YELLOW + C.BOLD, f"FAIL (DC {dc})")
    print(
        "  " + _c(C.MAGENTA, B.BULLET + " ")
        + _c(C.BOLD + color, f"[{label}] ")
        + _c(color, f"{detail} = {total}")
        + suffix
    )


# --- Prompt --------------------------------------------------------------


import re as _re

# Wrap ANSI escapes inside \001...\002 so readline / GNU editline does NOT
# count them as visible characters when computing cursor position. Without
# this, editing a long input line (or hitting home/end) lands the cursor in
# the wrong column on terminals that use readline.
_ANSI_RE = _re.compile(r"(\033\[[0-9;]*m)")


def _readline_safe(text: str) -> str:
    return _ANSI_RE.sub(lambda m: "\001" + m.group(1) + "\002", text)


def prompt(prefix: str = "> ") -> str:
    colored = _c(C.BRIGHT_CYAN + C.BOLD, prefix)
    safe = _readline_safe(colored)
    try:
        return input(safe)
    except EOFError:
        return "/quit"


# --- helpers -------------------------------------------------------------


def _visible_len(s: str) -> int:
    """Approx length ignoring ANSI escapes. We don't put escapes inside
    strings passed to box layout (we apply colors AFTER measuring), so this
    is mostly a safety net."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\033" and i + 1 < len(s) and s[i + 1] == "[":
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        out.append(s[i])
        i += 1
    return len("".join(out))
