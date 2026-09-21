"""Расчёт стоимости запросов по условным ценам задания."""
from dataclasses import dataclass

from app.config import PRICE_INPUT_PER_1M, PRICE_OUTPUT_PER_1M

REQUESTS_PER_DAY = 10_000
DAYS_PER_MONTH = 30


def request_cost(input_tokens: int, output_tokens: int,
                 price_in: float = PRICE_INPUT_PER_1M,
                 price_out: float = PRICE_OUTPUT_PER_1M) -> float:
    return input_tokens / 1_000_000 * price_in + output_tokens / 1_000_000 * price_out


@dataclass
class CostBreakdown:
    input_tokens: int
    output_tokens: int
    per_request: float
    input_share: float
    output_share: float

    def scale(self, requests: int) -> float:
        return self.per_request * requests

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "per_request": self.per_request,
            "input_share": self.input_share,
            "output_share": self.output_share,
            "per_1k_requests": self.scale(1_000),
            "per_day": self.scale(REQUESTS_PER_DAY),
            "per_month": self.scale(REQUESTS_PER_DAY * DAYS_PER_MONTH),
        }


def breakdown(input_tokens: int, output_tokens: int) -> CostBreakdown:
    cost_in = input_tokens / 1_000_000 * PRICE_INPUT_PER_1M
    cost_out = output_tokens / 1_000_000 * PRICE_OUTPUT_PER_1M
    total = cost_in + cost_out
    return CostBreakdown(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        per_request=total,
        input_share=cost_in / total if total else 0.0,
        output_share=cost_out / total if total else 0.0,
    )


def endpoint_cost(requests: int, avg_input: int, avg_output: int,
                  calls_per_request: float = 1.0) -> dict:
    """Стоимость эндпоинта за период. calls_per_request > 1 для агентов."""
    per_call = request_cost(avg_input, avg_output)
    per_request = per_call * calls_per_request
    total = per_request * requests
    return {
        "requests": requests,
        "avg_input": avg_input,
        "avg_output": avg_output,
        "calls_per_request": calls_per_request,
        "cost_per_request": per_request,
        "total_cost": total,
        "input_cost": avg_input / 1_000_000 * PRICE_INPUT_PER_1M * calls_per_request * requests,
        "output_cost": avg_output / 1_000_000 * PRICE_OUTPUT_PER_1M * calls_per_request * requests,
    }
