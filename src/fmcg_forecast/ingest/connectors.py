"""The connectors: two delivery shapes, one candidate form.

A connector does exactly one thing — turn a delivery into
candidate rows with every field's raw text kept. It judges
nothing: validation is the service's one path, shared by every
connector, so a row that would quarantine from a file drop
quarantines identically from an API push.

- **File drop** — CSV text with the header
  ``commodity,market,obs_date,driver,value,unit``. The batch
  header (source + as-of) is the delivery's provenance; rows
  inherit it.
- **API push** — a list of row objects, each carrying its own
  ``source`` and ``as_of`` alongside the figure fields. A row
  whose own provenance is missing, or disagrees with the
  batch's, is refused at the port (``missing_provenance``) —
  an API row never rides on another row's say-so.

A scheduled pull is a file drop the desk fetches on a cadence
instead of receiving; it enters through the same parser.
"""

from __future__ import annotations

import csv
import io

from fmcg_forecast.ingest.models import CandidateRow

FILE_HEADER = ("commodity", "market", "obs_date", "driver", "value", "unit")


def parse_file_drop(text: str) -> list[CandidateRow]:
    """Parse CSV text into candidate rows, raw text kept.

    A row with the wrong field count still becomes a
    candidate — with what text it carried — so the validation
    path can quarantine it as malformed rather than the
    parser silently dropping it.
    """
    rows: list[CandidateRow] = []
    reader = csv.reader(io.StringIO(text))
    records = [r for r in reader if r and any(c.strip() for c in r)]
    if records and tuple(c.strip() for c in records[0]) == FILE_HEADER:
        records = records[1:]
    for i, record in enumerate(records):
        cells = [c.strip() for c in record] + [""] * (6 - len(record))
        rows.append(
            CandidateRow(
                row_index=i,
                commodity=cells[0],
                market=cells[1],
                obs_date_text=cells[2],
                driver=cells[3],
                value_text=cells[4],
                unit=cells[5],
            )
        )
    return rows


def parse_api_push(payload: list[dict]) -> list[CandidateRow]:
    """Parse pushed row objects into candidate rows.

    Every field is stringified from the object as delivered;
    a missing field stays empty text, which the validation
    path reads as what it is — missing.
    """
    rows: list[CandidateRow] = []
    for i, item in enumerate(payload):
        def _text(key: str) -> str:
            value = item.get(key)
            return "" if value is None else str(value).strip()

        rows.append(
            CandidateRow(
                row_index=i,
                commodity=_text("commodity"),
                market=_text("market"),
                obs_date_text=_text("obs_date"),
                driver=_text("driver"),
                value_text=_text("value"),
                unit=_text("unit"),
                source_text=_text("source"),
                as_of_text=_text("as_of"),
            )
        )
    return rows
