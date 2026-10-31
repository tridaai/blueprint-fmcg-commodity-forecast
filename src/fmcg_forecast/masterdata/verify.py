"""Re-derive the master data layer from its artefacts.

- The chain is a line: each version's supersedes link
  names the version struck immediately before it, the
  sequences gapless from 1, the labels unique.
- Every version's diff is re-derived from the two
  states it spans — the superseded state (or genesis)
  and its own — and compared field by field.
- Genesis itself is re-derived from the catalogue, so
  a hand-edited genesis cannot quietly move the base
  every first diff is measured against.

Returns a list of problems; an empty list is a pass.
"""

from __future__ import annotations

from fmcg_forecast.masterdata.engine import diff_states, genesis_state
from fmcg_forecast.store import Store


def verify_masterdata(store: Store) -> list[str]:
    problems: list[str] = []
    genesis = genesis_state()
    versions = store.list_master_data_versions()

    seen_labels: set[str] = set()
    before = genesis
    expected_prior_id: str | None = None
    for position, version in enumerate(versions, start=1):
        if version.seq != position:
            problems.append(
                f"master data version {version.version_id} "
                f"carries sequence {version.seq} at position "
                f"{position} — the chain's strike order has "
                "a gap"
            )
        if version.supersedes_version_id != expected_prior_id:
            problems.append(
                f"master data version {version.version_id} "
                f"supersedes {version.supersedes_version_id}, "
                f"but the chain's prior version is "
                f"{expected_prior_id} — the chain is not a line"
            )
        if version.label in seen_labels:
            problems.append(
                f"label {version.label!r} names two versions "
                "in the chain"
            )
        seen_labels.add(version.label)
        if not version.edited_by or not version.edited_by.strip():
            problems.append(
                f"master data version {version.version_id} "
                "names no editor"
            )
        expected_diff = diff_states(before, version.state)
        if version.diff != expected_diff:
            problems.append(
                f"master data version {version.version_id} "
                "carries a diff that does not re-derive from "
                "the states it spans"
            )
        before = version.state
        expected_prior_id = version.version_id
    return problems
