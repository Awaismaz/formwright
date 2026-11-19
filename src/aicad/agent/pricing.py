"""Estimated compute cost of one model response, for the live run meter (the final charge uses the agent's own
cost report). Public list prices, USD per million tokens.

Cache writes have two prices: a 5-minute write costs 1.25x the input price (the "cache write" column) and a 1-hour
write costs 2x the input price. The Claude Code harness on a subscription login writes 1-hour entries by default,
so a usage report that splits ``cache_creation`` into ``ephemeral_1h_input_tokens`` / ``ephemeral_5m_input_tokens``
is priced per TTL (agent-cost report: pricing every write at the 5-minute rate under-read a $2.96 turn as $1.74)."""

from __future__ import annotations

from typing import Any

# (input, output, cache write, cache read). Most specific prefix first. Unknown models use the last row (Opus-class),
# so the meter errs towards stopping a run early, never towards overspending.
PRICES: list[tuple[str, tuple[float, float, float, float]]] = [
    ("claude-fable-5-2", (8.0, 40.0, 10.0, 0.20)),
    ("claude-mythos-5-2", (8.0, 40.0, 10.0, 0.20)),
    ("claude-fable", (10.0, 50.0, 12.5, 1.0)),
    ("claude-mythos", (10.0, 50.0, 12.5, 1.0)),
    ("claude-opus-5-5", (4.0, 20.0, 5.0, 0.20)),
    ("claude-opus", (5.0, 25.0, 6.25, 0.50)),
    ("claude-sonnet-5", (2.0, 10.0, 2.5, 0.10)),
    ("claude-sonnet", (3.0, 15.0, 3.75, 0.30)),
    ("claude-haiku-5", (0.10, 0.50, 0.125, 0.01)),
    ("claude-haiku", (1.0, 5.0, 1.25, 0.10)),
    ("", (5.0, 25.0, 6.25, 0.50)),
]


def usage_cost_usd(model: str | None, usage: dict[str, Any] | None) -> float:
    """Cost of one model response from its usage report (input, output and prompt-cache tokens)."""
    if not usage:
        return 0.0
    m = (model or "").lower()
    p_in, p_out, p_cw, p_cr = next(p for k, p in PRICES if not k or k in m)

    def n(key: str) -> float:
        v = usage.get(key) or 0
        return float(v) if isinstance(v, int | float) else 0.0

    cw = n("cache_creation_input_tokens")
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    one_h = split.get("ephemeral_1h_input_tokens") or 0
    one_h = min(float(one_h) if isinstance(one_h, int | float) else 0.0, cw)
    return (n("input_tokens") * p_in + n("output_tokens") * p_out + (cw - one_h) * p_cw + one_h * 2 * p_in
            + n("cache_read_input_tokens") * p_cr) / 1e6
