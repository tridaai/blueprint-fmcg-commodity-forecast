"""The scenario diff: fork against base, in code, to the paisa.

The diff is a pure function of the two stored forecast
artefacts. Both decompositions are exact (baseline + driver
contributions + events = P50) and a fork shares its base's
baseline by construction — the estimation is identical, only
the future input paths moved — so the per-driver differences
sum exactly to the P50 difference on every day. The arithmetic
is done in integer paise (every stored figure is rounded to
2dp), so the identity is exact, not approximate: any day whose
parts do not sum to its P50 difference is a defect, and the
verifier counts it.
"""

from __future__ import annotations

from fmcg_forecast.forecast.models import HORIZONS, Forecast
from fmcg_forecast.scenarios.models import ScenarioDiff, ScenarioDiffDay


def _paise(value: float) -> int:
    return int(round(value * 100))


def _inr(paise: int) -> float:
    return round(paise / 100, 2)


def compute_diff(
    scenario_id: str, base: Forecast, fork: Forecast
) -> tuple[ScenarioDiff, list[str]]:
    """The diff view, plus the list of identity problems found.

    Problems are returned (not raised) so the read path can show
    the diff alongside its own verdict; a clean scenario run has
    an empty list, and the verifier grades on it.
    """
    problems: list[str] = []
    if len(base.days) != len(fork.days):
        problems.append(
            f"base carries {len(base.days)} days, fork {len(fork.days)}"
        )
        return (
            ScenarioDiff(
                scenario_id=scenario_id,
                base_forecast_id=base.forecast_id,
                fork_forecast_id=fork.forecast_id,
                days=[],
                driver_totals={},
                events_total=0.0,
                p50_total=0.0,
                at_horizons={},
            ),
            problems,
        )

    driver_names: list[str] = []
    for forecast in (base, fork):
        for day in forecast.days:
            for name in day.contributions:
                if name not in driver_names:
                    driver_names.append(name)

    days: list[ScenarioDiffDay] = []
    totals_paise: dict[str, int] = {name: 0 for name in driver_names}
    events_total_paise = 0
    p50_total_paise = 0
    at_horizons: dict[str, float] = {}
    for i, (base_day, fork_day) in enumerate(zip(base.days, fork.days)):
        if base_day.forecast_date != fork_day.forecast_date:
            problems.append(
                f"day {i}: base date {base_day.forecast_date} != "
                f"fork date {fork_day.forecast_date}"
            )
            continue
        if _paise(fork_day.baseline) != _paise(base_day.baseline):
            problems.append(
                f"{base_day.forecast_date}: the fork's baseline "
                f"moved ({base_day.baseline} -> {fork_day.baseline}) "
                "— a scenario fork shares its base's estimation; "
                "only input paths may move"
            )
        contributions: dict[str, float] = {}
        day_parts = 0
        for name in driver_names:
            diff_paise = _paise(fork_day.contributions.get(name, 0.0)) - _paise(
                base_day.contributions.get(name, 0.0)
            )
            contributions[name] = _inr(diff_paise)
            totals_paise[name] += diff_paise
            day_parts += diff_paise
        events_paise = _paise(fork_day.events_adjustment) - _paise(
            base_day.events_adjustment
        )
        p50_paise = _paise(fork_day.p50) - _paise(base_day.p50)
        if day_parts + events_paise != p50_paise:
            problems.append(
                f"{base_day.forecast_date}: per-driver differences "
                f"sum to {_inr(day_parts + events_paise)}, != the "
                f"P50 difference {_inr(p50_paise)}"
            )
        events_total_paise += events_paise
        p50_total_paise += p50_paise
        days.append(
            ScenarioDiffDay(
                forecast_date=base_day.forecast_date,
                contributions=contributions,
                events_adjustment=_inr(events_paise),
                p50=_inr(p50_paise),
            )
        )
        if (i + 1) in HORIZONS:
            at_horizons[str(i + 1)] = _inr(p50_paise)

    diff = ScenarioDiff(
        scenario_id=scenario_id,
        base_forecast_id=base.forecast_id,
        fork_forecast_id=fork.forecast_id,
        days=days,
        driver_totals={name: _inr(v) for name, v in totals_paise.items()},
        events_total=_inr(events_total_paise),
        p50_total=_inr(p50_total_paise),
        at_horizons=at_horizons,
    )
    if sum(totals_paise.values()) + events_total_paise != p50_total_paise:
        problems.append(
            "the horizon totals do not sum to the total P50 difference"
        )
    return diff, problems
