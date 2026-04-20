"""Tests for the formatting facade.

Covers:
  - supports_color honors NO_COLOR and TTY detection
  - print_json round-trips Path/datetime through our default encoder
  - sparkline handles empty, constant, and mixed input
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from agent_os import formatting


def test_supports_color_respects_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert formatting.supports_color() is False


def test_supports_color_off_without_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    buf = io.StringIO()
    assert formatting.supports_color(buf) is False


def test_supports_color_on_with_force(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert formatting.supports_color() is True


def test_print_json_handles_paths_and_datetimes():
    buf = io.StringIO()
    data = {
        "path": Path("/tmp/example"),
        "when": datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        "tags": {"b", "a"},
    }
    formatting.print_json(data, stream=buf)
    parsed = json.loads(buf.getvalue())
    assert parsed["path"] == "/tmp/example"
    assert parsed["when"].startswith("2026-04-19T12:00:00")
    assert parsed["tags"] == ["a", "b"]


def test_sparkline_empty():
    assert formatting.sparkline([]) == ""


def test_sparkline_constant():
    # Flat series should be a single repeated character of length n
    out = formatting.sparkline([5, 5, 5, 5])
    assert len(out) == 4
    assert len(set(out)) == 1


def test_sparkline_varied():
    out = formatting.sparkline([1, 2, 3, 4, 8])
    # Highest value should use the tallest glyph
    assert out[-1] == "█"
    assert out[0] == "▁"
    assert len(out) == 5


def test_sparkline_ignores_none():
    out = formatting.sparkline([None, 1, 2, 3])
    assert len(out) == 3
