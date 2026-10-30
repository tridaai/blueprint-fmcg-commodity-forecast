"""The analytics workflow every surface shares.

Building a report is a computation, not an act: the service
recomputes the report from the store's artefacts of record and
stores it insert-only — the same store always lands on the same
content address, so re-building is a no-op that returns the
stored artefact. Views carry the artefact and its
re-performance problems: no surface offers a trend, an outcome
or a class aggregate without the verifier's reading of it.
"""

from __future__ import annotations

from fmcg_forecast.analytics.engine import compute_report
from fmcg_forecast.analytics.models import OpsReport
from fmcg_forecast.analytics.pack import AnalyticsPack, load_analytics_pack
from fmcg_forecast.analytics.verify import verify_report
from fmcg_forecast.store import Store


class AnalyticsNotFoundError(LookupError):
    """No ops report with that id."""


class AnalyticsService:
    def __init__(self, store: Store, pack: AnalyticsPack | None = None):
        self.store = store
        self.pack = pack or load_analytics_pack()

    def build_report(self) -> OpsReport:
        report = compute_report(self.store, self.pack)
        existing = self.store.get_ops_report(report.report_id)
        if existing is not None:
            return existing
        self.store.insert_ops_report(report)
        return report

    def get_report(self, report_id: str) -> OpsReport:
        report = self.store.get_ops_report(report_id)
        if report is None:
            raise AnalyticsNotFoundError(f"no ops report {report_id}")
        return report

    def list_reports(self) -> list[OpsReport]:
        return self.store.list_ops_reports()

    def report_view(self, report_id: str) -> dict:
        report = self.get_report(report_id)
        view = report.model_dump(mode="json")
        view["problems"] = verify_report(self.store, report)
        return view

    def verify_stored(self, report_id: str) -> list[str]:
        return verify_report(self.store, self.get_report(report_id))

    def verify_all(self) -> list[str]:
        problems: list[str] = []
        for report in self.store.list_ops_reports():
            for problem in verify_report(self.store, report):
                problems.append(f"{report.report_id}: {problem}")
        return problems
