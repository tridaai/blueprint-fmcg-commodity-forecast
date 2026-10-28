"""From levers to driver-input shifts, by the pack's stated rules.

A lever is stated in desk units — a percentage of arrivals, a
count of cover days. The engine consumes standardised driver
inputs. This module performs the scenario pack's conversions,
from the series' observed history up to the run's as_of (the same
history the engine estimated on), and records every statistic it
used on the run's AppliedShift artefacts — so a verifier can
re-perform each shift from the store and the pack alone, and a
reader can see exactly what a "10% arrivals drop" became.

The statistics, as the pack states them:

- arrivals: sd of log arrivals over every observed day of the
  series up to as_of; the shift is ln(1 + p/100) / sd.
- stock cover: sd of the stock level over the same days; the
  shift is days / sd.
- trade flow: sd of (imports - exports) over the days both are
  observed, and the last observed import flow; the shift is
  import_last x p/100 / sd.
- weather: the input is the raw index, so the deviation is the
  shift itself, applied with the pack's clip to the index range.
- sentiment: no conversion — the override is the path's starting
  value, handled by the engine's set_start mode.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np

from fmcg_forecast.scenarios.models import AppliedShift, LeverApplication
from fmcg_forecast.scenarios.pack import ScenarioPack
from fmcg_forecast.forecast.engine import SeriesSource


class ShiftError(RuntimeError):
    """A lever cannot be converted for this series."""


def _series_values(
    source: SeriesSource,
    commodity: str,
    market: str,
    driver: str,
    as_of: date,
) -> list[tuple[date, float]]:
    rows = source.series(commodity, market, driver, None, as_of)
    return [(r.obs_date, float(r.value)) for r in rows]


def compute_shift(
    source: SeriesSource,
    commodity: str,
    market: str,
    as_of: date,
    lever: LeverApplication,
    pack: ScenarioPack,
) -> AppliedShift:
    """The AppliedShift one numeric lever becomes for this series."""
    name = lever.lever
    value = lever.value
    if value is None:
        raise ShiftError(f"lever {name} carries no value")
    if name == "arrivals_shift_pct":
        points = _series_values(source, commodity, market, "arrivals", as_of)
        if len(points) < 2:
            raise ShiftError(
                f"{commodity}/{market} has no arrivals history to "
                "state an arrivals shift over"
            )
        logs = np.log(np.array([v for _, v in points]))
        sd = float(logs.std())
        if sd == 0.0:
            raise ShiftError("arrivals history has zero spread; the shift is not statable")
        shift = math.log(1.0 + value / 100.0) / sd
        return AppliedShift(
            lever=name,
            driver="arrivals",
            mode="add",
            value=shift,
            basis_stats={
                "pct": value,
                "sd_log_arrivals": sd,
                "history_obs": len(points),
                "history_last_date": points[-1][0].isoformat(),
            },
        )
    if name == "stock_cover_days":
        points = _series_values(source, commodity, market, "stock_level", as_of)
        if len(points) < 2:
            raise ShiftError(
                f"{commodity}/{market} has no stock-cover history "
                "to state a stock shift over"
            )
        levels = np.array([v for _, v in points])
        sd = float(levels.std())
        if sd == 0.0:
            raise ShiftError("stock-cover history has zero spread; the shift is not statable")
        return AppliedShift(
            lever=name,
            driver="stock_level",
            mode="add",
            value=value / sd,
            basis_stats={
                "days": value,
                "sd_stock_level": sd,
                "history_obs": len(points),
                "history_last_date": points[-1][0].isoformat(),
            },
        )
    if name == "trade_flow_shift_pct":
        imports = dict(_series_values(source, commodity, market, "import_flow", as_of))
        exports = dict(_series_values(source, commodity, market, "export_flow", as_of))
        common = sorted(set(imports) & set(exports))
        if len(common) < 2:
            raise ShiftError(
                f"{commodity}/{market} has no trade-flow history "
                "to state a trade shift over"
            )
        net = np.array([imports[d] - exports[d] for d in common])
        sd = float(net.std())
        if sd == 0.0:
            raise ShiftError("net trade flow has zero spread; the shift is not statable")
        import_last = imports[common[-1]]
        return AppliedShift(
            lever=name,
            driver="trade_flow",
            mode="add",
            value=import_last * (value / 100.0) / sd,
            basis_stats={
                "pct": value,
                "import_last": import_last,
                "import_last_date": common[-1].isoformat(),
                "sd_net_flow": sd,
                "history_obs": len(common),
            },
        )
    if name == "weather_deviation":
        return AppliedShift(
            lever=name,
            driver="weather_index",
            mode="add_clip",
            value=value,
            clip_min=pack.weather_index_min,
            clip_max=pack.weather_index_max,
            basis_stats={"deviation": value},
        )
    if name == "sentiment_override":
        return AppliedShift(
            lever=name,
            driver="sentiment",
            mode="set_start",
            value=value,
            basis_stats={"override": value},
        )
    raise ShiftError(f"lever {name} is not a numeric driver lever")
