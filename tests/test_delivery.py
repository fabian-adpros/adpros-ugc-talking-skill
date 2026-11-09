"""Delivery questions never read stdin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.config import DEFAULTS  # noqa: E402
from lib.delivery import resolve_delivery  # noqa: E402
from lib.nle import parse_editors  # noqa: E402


def _args(**kwargs):
    base = dict(yes=False, nle=None, review_storyboard=False, no_review_storyboard=False, storyboard_yes=False)
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_missing_answers_ask_instead_of_blocking():
    status, payload = resolve_delivery(_args(), {}, DEFAULTS)
    assert status == "ask"
    assert payload is None


def test_yes_uses_preset_defaults_without_a_storyboard_stop():
    status, payload = resolve_delivery(_args(yes=True), {}, DEFAULTS)
    assert status == "go"
    assert payload["editor_projects"] is False
    assert payload["storyboard_approved"] is True


def test_saved_answers_are_not_asked_again():
    plan = {
        "delivery": {
            "answered": True,
            "editor_projects": True,
            "editors": ["premiere"],
            "review_storyboard": False,
            "storyboard_approved": True,
        }
    }
    status, payload = resolve_delivery(_args(), plan, DEFAULTS)
    assert status == "go"
    assert payload["editors"] == ["premiere"]


def test_review_stops_until_storyboard_yes():
    status, payload = resolve_delivery(
        _args(nle="premiere,fcpx", review_storyboard=True),
        {},
        DEFAULTS,
    )
    assert status == "review"
    assert payload["storyboard_approved"] is False
    status, payload = resolve_delivery(
        _args(storyboard_yes=True),
        {"delivery": payload},
        DEFAULTS,
    )
    assert status == "go"
    assert payload["storyboard_approved"] is True


def test_nle_list_includes_resolve_and_capcut():
    assert parse_editors("premiere,fcpx,resolve") == {"premiere", "fcpx", "resolve"}
    assert parse_editors("capcut") == {"capcut"}
    assert parse_editors("none") == set()
    assert "otio" in parse_editors("all")


def test_delivery_round_trip_json():
    payload = {"answered": True, "editor_projects": True, "editors": ["resolve"], "review_storyboard": False, "storyboard_approved": True}
    assert json.loads(json.dumps(payload))["editors"] == ["resolve"]
