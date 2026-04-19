"""Shared formatting helpers for CLI output.

Most commands talk to this module rather than importing rich/plotext directly,
so we keep the dependency surface small and swappable. Two audiences:

  - humans at a terminal — rich tables/panels, plotext charts, colored output
  - programmatic callers (scripts, agents) — stable JSON via `print_json`

`supports_color()` and `should_use_rich()` are the single source of truth for
when to render with ANSI or fall back to plain text. Respects NO_COLOR and
non-TTY stdout, matching the convention already in status.py.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from typing import Any

# --- Capability detection -------------------------------------------------


def supports_color(stream=None) -> bool:
    """True when the target stream can render ANSI escapes.

    Respects NO_COLOR (https://no-color.org) and TTY detection.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    s = stream or sys.stdout
    try:
        return bool(s.isatty())
    except Exception:
        return False


def should_use_rich(stream=None) -> bool:
    """True when rich formatting is appropriate.

    rich itself degrades gracefully on non-TTYs, but we still gate on
    `supports_color` so piped output stays clean for grep/agents.
    """
    return supports_color(stream)


def terminal_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


# --- JSON emission --------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """Make Paths, datetimes, sets, and unknown objects JSON-serializable."""
    try:
        from datetime import date, datetime
        from pathlib import Path

        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, datetime | date):
            return obj.isoformat()
    except Exception:
        pass
    if isinstance(obj, set | frozenset):
        return sorted(obj)
    return str(obj)


def print_json(data: Any, *, stream=None) -> None:
    """Emit data as indented JSON. Stable schema is the caller's responsibility."""
    out = stream or sys.stdout
    out.write(json.dumps(data, indent=2, default=_json_default, sort_keys=False))
    out.write("\n")


# --- Rich-backed helpers (lazy imports) -----------------------------------


def _get_console(*, force_terminal: bool | None = None):
    from rich.console import Console

    return Console(force_terminal=force_terminal, no_color=not supports_color())


def human_table(
    rows: Iterable[Sequence[Any]],
    headers: Sequence[str],
    *,
    title: str | None = None,
    caption: str | None = None,
) -> None:
    """Render a table via rich. Rows are sequences in header order."""
    from rich.table import Table

    table = Table(title=title, caption=caption, header_style="bold")
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*(str(cell) if cell is not None else "" for cell in row))

    _get_console().print(table)


def human_panel(body: str, *, title: str | None = None, style: str | None = None) -> None:
    """Render a rich panel wrapping a string body."""
    from rich.panel import Panel

    panel = Panel(body, title=title, style=style or "")
    _get_console().print(panel)


def render_markdown(md: str) -> None:
    """Pretty-print markdown to the terminal via rich."""
    from rich.markdown import Markdown

    _get_console().print(Markdown(md))


# --- Sparklines (no dependency) -------------------------------------------

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[float]) -> str:
    """Return a unicode sparkline for `values`. Empty input yields empty string."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return ""
    lo = min(vals)
    hi = max(vals)
    span = hi - lo
    if span == 0:
        # Flat series — render the midpoint block across the width
        return _SPARK_CHARS[len(_SPARK_CHARS) // 2] * len(vals)
    buckets = len(_SPARK_CHARS) - 1
    out = []
    for v in vals:
        idx = round((v - lo) / span * buckets)
        out.append(_SPARK_CHARS[idx])
    return "".join(out)


# --- Plotext charts (lazy import) -----------------------------------------


def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str | None = None,
    height: int = 12,
) -> None:
    """Render a simple bar chart to stdout via plotext."""
    import plotext as plt

    plt.clear_figure()
    plt.bar(list(labels), list(values))
    if title:
        plt.title(title)
    plt.plotsize(min(terminal_width(), 100), height)
    plt.show()


def stacked_bar(
    labels: Sequence[str],
    series: dict[str, Sequence[float]],
    *,
    title: str | None = None,
    height: int = 14,
) -> None:
    """Render a stacked bar chart via plotext.

    `series` maps a label (e.g. agent id) to a list of values aligned with `labels`.
    """
    import plotext as plt

    plt.clear_figure()
    plt.stacked_bar(list(labels), [list(v) for v in series.values()], label=list(series.keys()))
    if title:
        plt.title(title)
    plt.plotsize(min(terminal_width(), 100), height)
    plt.show()
