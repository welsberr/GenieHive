from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from .config import ModelPrice


def calculate_estimated_cost_cents(
    model: str | None,
    usage: Mapping[str, int | None],
    prices: Mapping[str, ModelPrice],
) -> Decimal | None:
    """Calculate a model's cost in cents from normalized token usage.

    Prices are integer microdollars per million tokens. The exact model ID must
    be present in ``prices``; no family or provider fallback is attempted.
    """
    if not model or model not in prices:
        return None
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    input_tokens = max(0, int(input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    price = prices[model]
    microdollars = (
        input_tokens * price.input_microdollars_per_million
        + output_tokens * price.output_microdollars_per_million
    )
    # 1 cent = 10,000 microdollars; divide by 1,000,000 tokens per price unit.
    cents = Decimal(microdollars) / Decimal(10_000_000_000)
    return cents.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
