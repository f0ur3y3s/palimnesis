"""Budgets (contracts §2; D8, D14.3, D14.4, D14.11). Literal values from the decisions."""

from __future__ import annotations

import pytest

from palimnesis.budget import BudgetError, BudgetPolicy, check_fixed, check_floor, plan_budget

POLICY = BudgetPolicy()


@pytest.mark.parametrize(
    ("n_ctx", "input_budget"),
    [(32768, 24320), (65536, 48000)],  # D8 and D14.3
)
def test_input_budget_is_capped_by_capacity_minus_reserve_and_margin(n_ctx, input_budget):
    b = plan_budget(n_ctx, client_limit=8192, policy=POLICY)

    assert (b.reserve, b.margin, b.input_budget) == (8192, 256, input_budget)
    assert b.input_budget + b.reserve + b.margin <= n_ctx


def test_catalog_and_recall_slots_are_reserved_from_the_input_budget():
    b = plan_budget(32768, client_limit=8192, policy=POLICY)

    # D14.4: P = min(1024, 5% of 24,320) = 1024; Q = min(4096, 10% of 24,320) = 2432
    assert (b.catalog, b.recall) == (1024, 2432)


@pytest.mark.parametrize(
    ("client_limit", "reserve", "rewrite"),
    [(None, 8192, 8192), (32000, 8192, 8192), (8192, 8192, None), (1000, 1000, None), (0, 8192, 8192)],
)
def test_generation_reserve_and_upstream_limit_rewrite(client_limit, reserve, rewrite):
    b = plan_budget(65536, client_limit=client_limit, policy=POLICY)

    assert (b.reserve, b.rewrite_limit) == (reserve, rewrite)


def test_a_small_client_limit_frees_input_room():
    assert plan_budget(32768, client_limit=1000, policy=POLICY).input_budget == 31512


def test_measured_drift_widens_the_margin():
    b = plan_budget(32768, client_limit=8192, policy=POLICY, extra_margin=300)

    assert (b.margin, b.input_budget) == (556, 24020)


def test_fixed_input_that_fits_passes():
    check_fixed(plan_budget(32768, client_limit=8192, policy=POLICY), fixed_tokens=20000)


def test_fixed_input_that_cannot_fit_names_every_term():
    b = plan_budget(32768, client_limit=8192, policy=POLICY)

    with pytest.raises(BudgetError) as e:
        check_fixed(b, fixed_tokens=24321)

    assert e.value.terms == {"fixed": 24321, "reserve": 8192, "margin": 256, "n_ctx": 32768,
                             "input_budget": 24320}
    for name in ("24321", "8192", "256", "32768"):
        assert name in str(e.value)


def test_capacity_too_small_for_any_input_is_a_budget_error():
    with pytest.raises(BudgetError):
        plan_budget(8000, client_limit=8192, policy=POLICY)


def test_startup_floor_requires_room_for_a_minimum_recent_window():
    check_floor(32768, fixed_min=5000, client_limit=8192, policy=POLICY)

    with pytest.raises(BudgetError) as e:
        check_floor(16384, fixed_min=5000, client_limit=8192, policy=POLICY)
    # 5000 + 4096 + 8192 + 256 = 17544 > 16384
    assert e.value.terms["min_recent"] == 4096
