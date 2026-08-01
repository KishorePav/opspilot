from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from opspilot.investigation.models import ModelUsage, UsageSummary

_ONE_MILLION = Decimal("1000000")
_COST_PRECISION = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    """Explicit, versioned rates used only to estimate model-call cost."""

    model: str
    version: str
    input_usd_per_million: Decimal
    cached_input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.version.strip():
            raise ValueError("pricing model and version must not be empty")
        if min(
            self.input_usd_per_million,
            self.cached_input_usd_per_million,
            self.output_usd_per_million,
        ) < 0:
            raise ValueError("pricing rates cannot be negative")

    def estimate(self, records: Sequence[ModelUsage]) -> Decimal:
        cost = Decimal("0")
        for record in records:
            if record.model != self.model:
                raise ValueError(
                    f"pricing policy for {self.model!r} cannot price {record.model!r}"
                )
            non_cached = record.input_tokens - record.cached_input_tokens
            cost += (
                Decimal(non_cached) * self.input_usd_per_million
                + Decimal(record.cached_input_tokens)
                * self.cached_input_usd_per_million
                + Decimal(record.output_tokens) * self.output_usd_per_million
            ) / _ONE_MILLION
        return cost.quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)


def summarize_usage(
    records: Sequence[ModelUsage],
    *,
    model_calls: int,
    pricing: PricingPolicy | None,
) -> UsageSummary:
    estimated_cost = pricing.estimate(records) if pricing is not None else None
    return UsageSummary(
        models=sorted({record.model for record in records}),
        model_calls=model_calls,
        input_tokens=sum(record.input_tokens for record in records),
        cached_input_tokens=sum(record.cached_input_tokens for record in records),
        output_tokens=sum(record.output_tokens for record in records),
        reasoning_tokens=sum(record.reasoning_tokens for record in records),
        total_tokens=sum(record.total_tokens for record in records),
        estimated_cost_usd=estimated_cost,
        pricing_version=pricing.version if pricing is not None else None,
    )
