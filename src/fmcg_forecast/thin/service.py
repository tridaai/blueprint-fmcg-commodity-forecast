"""The thin-data workflow every surface shares.

Assessing a forecast is a computation, not an act: the service
recomputes the assessment from the store and the pinned
forecast and stores it insert-only — the same forecast always
lands on the same content address, so re-assessing is a no-op
that returns the stored artefact. Views carry the artefact,
its named gaps verbatim, and its re-performance problems: no
surface offers a tier without the evidence and the gaps that
bound it.
"""

from __future__ import annotations

from fmcg_forecast.forecast.service import ForecastNotFoundError
from fmcg_forecast.store import Store
from fmcg_forecast.thin.engine import ThinDataError, compute_assessment
from fmcg_forecast.thin.models import ThinAssessment
from fmcg_forecast.thin.pack import ThinDataPack, load_thin_data_pack
from fmcg_forecast.thin.verify import verify_assessment, verify_tier_claim


class ThinDataNotFoundError(LookupError):
    """No assessment with that id."""


class ThinDataService:
    def __init__(self, store: Store, pack: ThinDataPack | None = None):
        self.store = store
        self.pack = pack or load_thin_data_pack()

    def assess_forecast(self, forecast_id: str) -> ThinAssessment:
        forecast = self.store.get_forecast(forecast_id)
        if forecast is None:
            raise ForecastNotFoundError(f"unknown forecast {forecast_id}")
        assessment = compute_assessment(self.store, forecast, self.pack)
        existing = self.store.get_thin_assessment(assessment.assessment_id)
        if existing is not None:
            return existing
        self.store.insert_thin_assessment(assessment)
        return assessment

    def assess_series(self, commodity: str, market: str) -> ThinAssessment:
        """Assess the series' head forecast (the dashboards'
        head rule: official outranks draft, then greatest
        as_of, then greatest content address)."""
        candidates = self.store.list_forecasts(commodity, market)
        if not candidates:
            raise ThinDataError(
                f"no forecast on record for {commodity}/{market} to assess"
            )
        head = max(
            candidates,
            key=lambda f: (f.status == "official", f.as_of, f.forecast_id),
        )
        return self.assess_forecast(head.forecast_id)

    def get_assessment(self, assessment_id: str) -> ThinAssessment:
        assessment = self.store.get_thin_assessment(assessment_id)
        if assessment is None:
            raise ThinDataNotFoundError(f"no assessment {assessment_id}")
        return assessment

    def list_assessments(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[ThinAssessment]:
        return self.store.list_thin_assessments(commodity, market)

    def assessment_view(self, assessment_id: str) -> dict:
        assessment = self.get_assessment(assessment_id)
        view = assessment.model_dump(mode="json")
        view["problems"] = verify_assessment(self.store, assessment)
        return view

    def forecast_view(self, forecast_id: str) -> dict:
        """The assessment for one forecast, assessed on read —
        the shape consumer surfaces state: the tier per horizon
        and every named gap, with the window evidence behind
        them."""
        assessment = self.assess_forecast(forecast_id)
        return self.assessment_view(assessment.assessment_id)

    def verify_stored(self, assessment_id: str) -> list[str]:
        return verify_assessment(self.store, self.get_assessment(assessment_id))

    def verify_all(self) -> list[str]:
        problems: list[str] = []
        for assessment in self.store.list_thin_assessments():
            for problem in verify_assessment(self.store, assessment):
                problems.append(f"{assessment.assessment_id}: {problem}")
        return problems

    def verify_claim(
        self, forecast_id: str, horizon_days: int, claimed_tier: str
    ) -> list[str]:
        assessment = self.assess_forecast(forecast_id)
        return verify_tier_claim(
            self.store, assessment, horizon_days, claimed_tier
        )
