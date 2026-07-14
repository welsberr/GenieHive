from decimal import Decimal

from geniehive_control.budgeting import calculate_estimated_cost_cents
from geniehive_control.config import ModelPrice


PRICES = {
    "test-model": ModelPrice(
        input_microdollars_per_million=1_000_000,
        output_microdollars_per_million=2_000_000,
    )
}


def test_cost_uses_exact_model_and_rounds_to_cents() -> None:
    result = calculate_estimated_cost_cents(
        "test-model",
        {"prompt_tokens": 1_000, "completion_tokens": 500},
        PRICES,
    )

    assert result == Decimal("0.20")


def test_unknown_model_does_not_fall_back_to_another_price() -> None:
    assert calculate_estimated_cost_cents(
        "test-model-alias",
        {"prompt_tokens": 1, "completion_tokens": 1},
        PRICES,
    ) is None


def test_zero_usage_is_a_known_zero_cost() -> None:
    assert calculate_estimated_cost_cents(
        "test-model",
        {"prompt_tokens": 0, "completion_tokens": 0},
        PRICES,
    ) == Decimal("0.00")


def test_missing_usage_is_unknown_cost() -> None:
    assert calculate_estimated_cost_cents("test-model", {}, PRICES) is None
