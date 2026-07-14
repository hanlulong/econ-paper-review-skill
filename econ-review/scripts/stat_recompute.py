#!/usr/bin/env python3
"""Recompute bounded statistical and accounting checks from declared numeric inputs."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_bytes, strict_json_load  # noqa: E402


def decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def recompute(check: dict[str, Any]) -> dict[str, Any]:
    kind = check.get("type")
    tolerance = decimal(check.get("tolerance", "0.000001"), "tolerance")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    with localcontext() as context:
        context.prec = 40
        if kind == "t_from_beta_se":
            beta, se = decimal(check.get("beta"), "beta"), decimal(check.get("se"), "se")
            if se <= 0:
                raise ValueError("se must be positive")
            value = beta / se
        elif kind == "f_from_t":
            t_value = decimal(check.get("t"), "t")
            value = t_value * t_value
        elif kind == "share_from_count":
            count, total = decimal(check.get("count"), "count"), decimal(check.get("total"), "total")
            if total <= 0:
                raise ValueError("total must be positive")
            value = count / total
            percent = check.get("percent", True)
            if not isinstance(percent, bool):
                raise ValueError("percent must be a boolean")
            if percent:
                value *= 100
        elif kind == "residual_df":
            n, parameters = decimal(check.get("n"), "n"), decimal(check.get("parameters"), "parameters")
            value = n - parameters
        elif kind == "sum":
            values = check.get("values")
            if not isinstance(values, list) or not values:
                raise ValueError("values must be a non-empty array")
            value = sum((decimal(item, "values item") for item in values), Decimal(0))
        elif kind == "n_drift":
            expected = decimal(check.get("expected"), "expected")
            observed = decimal(check.get("observed"), "observed")
            value = observed - expected
        elif kind == "grim_mean":
            if check.get("reported") is not None:
                raise ValueError("grim_mean derives compatibility from mean and n; omit reported")
            mean, n = decimal(check.get("mean"), "mean"), decimal(check.get("n"), "n")
            if n <= 0 or n != n.to_integral_value():
                raise ValueError("n must be a positive integer")
            decimals = check.get("decimals", 2)
            if not isinstance(decimals, int) or isinstance(decimals, bool):
                raise ValueError("decimals must be an integer")
            if decimals < 0 or decimals > 12:
                raise ValueError("decimals must be between 0 and 12")
            scaled = mean * n
            rounding_slack = Decimal("0.5") * (Decimal(10) ** (-decimals)) * n
            distance = abs(scaled - scaled.to_integral_value())
            value = distance
            check = {**check, "reported": 0, "tolerance": str(rounding_slack)}
            tolerance = rounding_slack
        else:
            raise ValueError(f"unsupported check type: {kind!r}")

        reported_raw = check.get("reported")
        reported = decimal(reported_raw, "reported") if reported_raw is not None else None
        difference = abs(value - reported) if reported is not None else None
        status = "match" if difference is not None and difference <= tolerance else (
            "mismatch" if difference is not None else "recomputed"
        )
        result = {
            "id": check.get("id"),
            "type": kind,
            "recomputed": str(value.normalize()),
            "reported": None if reported is None else str(reported.normalize()),
            "absolute_difference": None if difference is None else str(difference.normalize()),
            "tolerance": str(tolerance.normalize()),
            "status": status,
            "source_locator": check.get("source_locator"),
        }
        if kind == "grim_mean":
            result["interpretation"] = (
                "compatible with an integer-valued sample mean at the declared precision"
                if status == "match"
                else "not compatible with an integer-valued sample mean at the declared precision"
            )
        return result


def run(payload: dict[str, Any]) -> dict[str, Any]:
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("input must contain a non-empty checks array")
    results = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"checks[{index}] must be an object")
        try:
            results.append(recompute(check))
        except ValueError as exc:
            raise ValueError(f"checks[{index}]: {exc}") from exc
    return {
        "schema_version": "0.1",
        "results": results,
        "counts": {
            status: sum(result["status"] == status for result in results)
            for status in ("match", "mismatch", "recomputed")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing a checks array")
    parser.add_argument("--output", type=Path, help="Write JSON output here; stdout otherwise")
    args = parser.parse_args()
    try:
        payload = strict_json_load(args.input)
        if not isinstance(payload, dict):
            raise ValueError("input root must be an object")
        rendered = json.dumps(run(payload), indent=2) + "\n"
        if args.output:
            atomic_write_bytes(
                args.output.parent,
                args.output.name,
                rendered.encode("utf-8"),
            )
        else:
            print(rendered, end="")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(1, f"stat recomputation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
