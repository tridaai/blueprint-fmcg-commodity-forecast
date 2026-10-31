"""The master data service — versions struck by named
editors, the standing state, coverage re-derivation.

The strike-time rules, judged here in code:

- The editor holds a standing desk-head grant under
  the access pack — the pack's master-data right. An
  ungranted name, a trader, a viewer: refused.
- The struck state's diff against the standing state
  is computed here and carried on the version; an
  empty diff is refused.
- Labels are unique across the chain; the version
  supersedes exactly the version standing at strike
  time, so the chain is a line by construction.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.access.pack import load_access_pack
from fmcg_forecast.access.service import AccessService
from fmcg_forecast.masterdata.engine import (
    MasterDataError,
    coverage_report,
    diff_states,
    genesis_state,
)
from fmcg_forecast.masterdata.models import (
    MasterDataState,
    MasterDataVersion,
    master_data_version_content_id,
)
from fmcg_forecast.masterdata.pack import MasterDataPack, load_masterdata_pack
from fmcg_forecast.store import Store


class MasterDataNotFoundError(LookupError):
    """No master data artefact with that id."""


class MasterDataValidationError(ValueError):
    """A master data strike the pack refuses."""


class MasterDataService:
    def __init__(self, store: Store, pack: MasterDataPack | None = None):
        self.store = store
        self.pack = pack or load_masterdata_pack()
        self.genesis = genesis_state()

    # -- the standing state --------------------------------------------

    def standing_version(self) -> MasterDataVersion | None:
        versions = self.store.list_master_data_versions()
        return versions[-1] if versions else None

    def standing_state(self) -> MasterDataState:
        version = self.standing_version()
        return version.state if version else self.genesis

    def standing(self) -> dict:
        version = self.standing_version()
        return {
            "state": version.state if version else self.genesis,
            "label": version.label if version else "genesis",
            "source_version_id": version.version_id if version else None,
        }

    # -- strikes ---------------------------------------------------------

    def strike_version(
        self,
        label: str,
        state: MasterDataState | dict,
        edited_by: str,
        edited_on: date,
    ) -> MasterDataVersion:
        if not label or not label.strip():
            raise MasterDataValidationError("a version must be labelled")
        label = label.strip()
        if not edited_by or not edited_by.strip():
            raise MasterDataValidationError("an editor must be named")
        edited_by = edited_by.strip()
        if isinstance(state, dict):
            try:
                state = MasterDataState.model_validate(state)
            except ValueError as exc:
                raise MasterDataValidationError(str(exc)) from exc
        grant = AccessService(self.store).standing_grant(edited_by)
        access_pack = load_access_pack()
        if (
            grant is None
            or grant.role is None
            or not access_pack.role_scope(grant.role).may_edit_master_data
        ):
            raise MasterDataValidationError(
                f"editor {edited_by!r} holds no standing grant "
                "with the master-data right — a version is "
                "struck by a desk head, named"
            )
        versions = self.store.list_master_data_versions()
        if any(v.label == label for v in versions):
            raise MasterDataValidationError(
                f"label {label!r} already names a version in "
                "the chain — labels are unique"
            )
        standing = versions[-1] if versions else None
        before = standing.state if standing else self.genesis
        diff = diff_states(before, state)
        if not diff:
            raise MasterDataValidationError(
                "the struck state changes nothing against the "
                "standing state — a version that moves "
                "nothing is not a version"
            )
        version = MasterDataVersion(
            version_id="pending",
            seq=len(versions) + 1,
            label=label,
            state=state,
            diff=diff,
            supersedes_version_id=standing.version_id if standing else None,
            edited_by=edited_by,
            edited_on=edited_on,
            access_pack_version=access_pack.version,
            pack_version=self.pack.version,
        )
        version = version.model_copy(
            update={"version_id": master_data_version_content_id(version)}
        )
        self.store.insert_master_data_version(version)
        return version

    def get_version(self, version_id: str) -> MasterDataVersion:
        version = self.store.get_master_data_version(version_id)
        if version is None:
            raise MasterDataNotFoundError(
                f"no master data version {version_id}"
            )
        return version

    def version_view(self, version: MasterDataVersion) -> dict:
        standing = self.standing_version()
        payload = version.model_dump(mode="json")
        payload["standing"] = bool(
            standing and standing.version_id == version.version_id
        )
        return payload

    # -- coverage re-derivation -------------------------------------------

    def coverage(
        self,
        commodity: str,
        market: str,
        as_of: date,
        version_id: str | None = None,
    ) -> dict:
        """The thin windows' verdicts under genesis and
        under the standing (or a named) version."""
        if version_id is not None:
            target = self.get_version(version_id)
            after = target.state
            after_label = target.label
        else:
            after = self.standing_state()
            standing = self.standing_version()
            after_label = standing.label if standing else "genesis"
        try:
            report = coverage_report(
                self.store, commodity, market, as_of,
                self.genesis, after,
            )
        except MasterDataError as exc:
            raise MasterDataValidationError(str(exc)) from exc
        report["before_label"] = "genesis"
        report["after_label"] = after_label
        return report
