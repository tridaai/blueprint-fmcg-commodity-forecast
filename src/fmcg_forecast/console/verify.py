"""Re-performance for the console's artefacts.

Every check recomputes from the store and the pack, and
names the disagreement:

- a *rejection* re-performs when its content address
  recomputes, its reason is in the pack's vocabulary, its
  forecast exists, and no approval stands against the same
  forecast — an approval and a rejection coexisting is a
  record the act discipline makes impossible, so its presence
  is tamper evidence, graded as such;
- a *triage act* re-performs when its content address
  recomputes, its event exists, and an amend's replacement
  exists and is not the event itself;
- a *pre-flight report* re-performs when it recomputes
  field-for-field from the store under its named pack, and
  any forecast pinning it carries exactly its named gaps;
- the *set-level discipline* walks every stored act and
  report and collects the above, plus the forecasts whose
  pins point at reports that do not exist.
"""

from __future__ import annotations

from fmcg_forecast.console.engine import compute_preflight
from fmcg_forecast.console.models import (
    EventTriageAct,
    ForecastRejection,
    PreflightReport,
    preflight_content_id,
    rejection_content_id,
    triage_act_content_id,
)
from fmcg_forecast.console.pack import load_console_pack


def verify_rejection(store, rejection: ForecastRejection) -> list[str]:
    problems: list[str] = []
    if rejection_content_id(rejection) != rejection.rejection_id:
        problems.append(
            f"rejection {rejection.rejection_id}: content address does "
            "not recompute — the act was altered after it was struck"
        )
    try:
        pack = load_console_pack(rejection.pack_version)
    except ValueError:
        problems.append(
            f"rejection {rejection.rejection_id}: unknown console pack "
            f"version {rejection.pack_version!r}"
        )
        return problems
    if rejection.reason not in pack.rejection_reasons:
        problems.append(
            f"rejection {rejection.rejection_id}: reason "
            f"{rejection.reason!r} is not in the pack's vocabulary"
        )
    if rejection.reason == "other_stated_reason" and not rejection.note.strip():
        problems.append(
            f"rejection {rejection.rejection_id}: reason "
            "other_stated_reason without the reason spelled out in "
            "the note"
        )
    forecast = store.get_forecast(rejection.forecast_id)
    if forecast is None:
        problems.append(
            f"rejection {rejection.rejection_id}: forecast "
            f"{rejection.forecast_id} does not exist"
        )
    elif store.get_approval(rejection.forecast_id) is not None:
        problems.append(
            f"rejection {rejection.rejection_id}: an approval stands "
            f"against forecast {rejection.forecast_id} — approval and "
            "rejection cannot coexist under the act discipline"
        )
    return problems


def verify_triage_act(store, act: EventTriageAct) -> list[str]:
    problems: list[str] = []
    if triage_act_content_id(act) != act.act_id:
        problems.append(
            f"triage act {act.act_id}: content address does not "
            "recompute — the act was altered after it was struck"
        )
    if store.get_market_event(act.event_id) is None:
        problems.append(
            f"triage act {act.act_id}: event {act.event_id} does not "
            "exist"
        )
    if act.act == "amend":
        if act.replacement_event_id is None:
            problems.append(
                f"triage act {act.act_id}: an amend without a "
                "replacement declaration"
            )
        elif act.replacement_event_id == act.event_id:
            problems.append(
                f"triage act {act.act_id}: an amend whose replacement "
                "is the event itself"
            )
        elif store.get_market_event(act.replacement_event_id) is None:
            problems.append(
                f"triage act {act.act_id}: replacement "
                f"{act.replacement_event_id} does not exist"
            )
    elif act.replacement_event_id is not None:
        problems.append(
            f"triage act {act.act_id}: a {act.act} act carrying a "
            "replacement — only an amend replaces"
        )
    return problems


def verify_preflight(store, report: PreflightReport) -> list[str]:
    problems: list[str] = []
    if preflight_content_id(report) != report.report_id:
        problems.append(
            f"preflight {report.report_id}: content address does not "
            "recompute — the report was altered after it was struck"
        )
    try:
        pack = load_console_pack(report.pack_version)
    except ValueError:
        problems.append(
            f"preflight {report.report_id}: unknown console pack "
            f"version {report.pack_version!r}"
        )
        return problems
    try:
        recomputed = compute_preflight(
            store, report.commodity, report.market, report.as_of, pack
        )
    except Exception as exc:  # the series left the catalogue
        problems.append(f"preflight {report.report_id}: {exc}")
        return problems
    if recomputed.model_dump(mode="json") != report.model_dump(mode="json"):
        problems.append(
            f"preflight {report.report_id}: does not re-perform from "
            "the store — a driver state, the sentiment line, the "
            "coverage or the gap list disagrees with the record"
        )
    return problems


def verify_console(store) -> list[str]:
    """The set-level discipline across every console artefact."""
    problems: list[str] = []
    for rejection in store.list_forecast_rejections():
        for problem in verify_rejection(store, rejection):
            problems.append(problem)
    for act in store.list_event_triage_acts():
        for problem in verify_triage_act(store, act):
            problems.append(problem)
    for report in store.list_preflight_reports():
        for problem in verify_preflight(store, report):
            problems.append(problem)
    for forecast in store.list_forecasts():
        if forecast.preflight is None:
            continue
        report = store.get_preflight_report(forecast.preflight.preflight_id)
        if report is None:
            problems.append(
                f"forecast {forecast.forecast_id}: pins preflight "
                f"{forecast.preflight.preflight_id}, which does not "
                "exist"
            )
            continue
        if forecast.preflight.gaps != report.gaps:
            problems.append(
                f"forecast {forecast.forecast_id}: carries gaps that "
                "are not exactly its pinned preflight's named gaps"
            )
        if (report.commodity, report.market, report.as_of) != (
            forecast.commodity,
            forecast.market,
            forecast.as_of,
        ):
            problems.append(
                f"forecast {forecast.forecast_id}: pins a preflight "
                "struck for another series or another as-of"
            )
    return problems
