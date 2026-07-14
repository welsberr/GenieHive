from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from typing import Mapping

from .config import ModelPrice


class TokenBudgetExceeded(RuntimeError):
    status_code = 429

    def __init__(self, *, key_id: str, used_tokens: int, limit: int) -> None:
        self.key_id = key_id
        self.used_tokens = used_tokens
        self.limit = limit
        super().__init__(
            f"monthly token limit exhausted for key '{key_id}' "
            f"({used_tokens}/{limit} tokens used)"
        )


def monthly_period_start(now: float, reset_day: int) -> float:
    """Return the UTC epoch for the current monthly reset boundary."""
    current = datetime.fromtimestamp(now, tz=timezone.utc)
    reset_day = max(1, min(reset_day, 31))
    current_reset_day = min(reset_day, monthrange(current.year, current.month)[1])
    if current.day < current_reset_day:
        previous_last = current.replace(day=1) - timedelta(days=1)
        year, month = previous_last.year, previous_last.month
        current_reset_day = min(reset_day, monthrange(year, month)[1])
        current = current.replace(year=year, month=month, day=current_reset_day)
    else:
        current = current.replace(day=current_reset_day)
    return current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


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
