"""Development runs after R33 (D69-D71): arm-4 variants with the R33 changes, and ho2's
tasks taking development configurations once ho2 has been judged (D69). Pure functions;
nothing here runs OpenCode, a proxy or a model."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import needle  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))


def test_a4_tr_is_the_frozen_arm_4_plus_turn_protection_and_retrieval_r2():
    cfg = needle.CONFIGS["a4-tr"]
    assert cfg == dict(needle.CONFIGS["a4-d43"], protect_turn=True, retrieval="r2")
    assert needle.proxy_settings(cfg) == dict(needle.proxy_settings(needle.CONFIGS["a4-d43"]),
                                              protect_turn=True, retrieval="r2")


def test_arm_4_takes_a_development_config_under_its_own_label():
    info = task_run.resolve_arm(4, "a4-tr", "development")
    assert (info["arm"], info["label"], info["config"]) == (4, "a4-tr", "a4-tr")
    assert info["cfg"] == needle.CONFIGS["a4-tr"]
    # Without --config, arm 4 is still the frozen a4-d43 under the label a4.
    assert task_run.resolve_arm(4, None, "development")["label"] == "a4"


def test_ho2_tasks_take_development_configs_after_their_gate():
    assert task_run.resolve_arm(4, "a4-tr", "heldout2")["label"] == "a4-tr"
    assert task_run.resolve_arm(5, "a5-B", "heldout2")["label"] == "a5-B"


def test_the_first_held_out_set_still_runs_only_the_frozen_arms():
    with pytest.raises(ValueError):
        task_run.resolve_arm(4, "a4-tr", "heldout")
    with pytest.raises(ValueError, match="arm 4"):
        task_run.resolve_arm(4, "a5-B", "development")


def test_a4_trn_is_a4_tr_plus_2048_tokens_of_working_notes():
    assert needle.CONFIGS["a4-trn"] == dict(needle.CONFIGS["a4-tr"], notes_tokens=2048)
    assert needle.proxy_settings(needle.CONFIGS["a4-trn"])["notes_tokens"] == 2048
