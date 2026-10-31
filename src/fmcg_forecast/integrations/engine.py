"""The integrations engine: pure folds over artefacts.

Everything here is a function of stored artefacts and a
stated instant — no clock reads, no network, no state.
The board-pack fold reads the same store the API reads
and renders each section exactly as the pack states:
figures copied from the artefacts' own fields, floats
rendered by the CSV writer's stated rule, rows in a
stated order. The same store built for the same as-of
renders the same file set byte for byte — the build
instant stands on the artefact as metadata, never in
the bytes — which is what makes a pack re-performable,
a job's output byte-identical to the synchronous
build, and a tampered file detectable against its
manifest.

The PDF summary is rendered in-repo as a stated,
deterministic text PDF: fixed page geometry, one
embedded standard font, no timestamps, no
compression — the same pack always renders the same
bytes, and the manifest hashes them like any other
file.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import date, datetime

from fmcg_forecast.console.engine import triage_states
from fmcg_forecast.integrations.models import (
    BoardPack,
    PackFile,
    board_pack_content_id,
)
from fmcg_forecast.integrations.pack import IntegrationsPack
from fmcg_forecast.store import Store


def fmt(value) -> str:
    """The CSV cell rule: values as the artefacts state
    them — dates ISO, floats via repr's shortest round
    trip, booleans as true/false, None as empty."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def render_csv(columns: list[str], rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([fmt(row.get(column)) for column in columns])
    return buffer.getvalue()


def section_rows(store: Store, pack: IntegrationsPack, as_of: date) -> dict[str, list[dict]]:
    """Fold the four sections from the standing artefacts."""
    rows: dict[str, list[dict]] = {}

    official: list[dict] = []
    for forecast in store.list_forecasts():
        approval = store.get_approval(forecast.forecast_id)
        if approval is None or approval.decided_on > as_of:
            continue
        for day in forecast.days:
            official.append(
                {
                    "forecast_id": forecast.forecast_id,
                    "commodity": forecast.commodity,
                    "market": forecast.market,
                    "forecast_as_of": forecast.as_of,
                    "approved_by": approval.approver,
                    "decided_on": approval.decided_on,
                    "forecast_date": day.forecast_date,
                    "p10_inr": day.p10,
                    "p50_inr": day.p50,
                    "p90_inr": day.p90,
                }
            )
    official.sort(
        key=lambda r: (r["commodity"], r["market"], r["forecast_id"], r["forecast_date"])
    )
    rows["official_forecasts"] = official

    accuracy: list[dict] = []
    for record in store.list_accuracy_records():
        accuracy.append(
            {
                "record_id": record.record_id,
                "commodity": record.commodity,
                "market": record.market,
                "horizon_days": record.horizon_days,
                "n_results": record.n_results,
                "n_days": record.n_days,
                "mae_inr": record.mae,
                "mape_pct": record.mape,
                "bias_inr": record.bias,
                "coverage": record.coverage,
                "degraded": record.degraded,
            }
        )
    accuracy.sort(key=lambda r: (r["commodity"], r["market"], r["horizon_days"]))
    rows["accuracy_summary"] = accuracy

    states = triage_states(store)
    events: list[dict] = []
    for event in store.list_market_events():
        if event.window_start > as_of:
            continue
        if event.window_end is not None and event.window_end < as_of:
            continue
        state = states.get(event.event_id, "declared")
        if state == "retired":
            continue
        events.append(
            {
                "event_id": event.event_id,
                "event_class": event.event_class,
                "commodity": event.commodity,
                "window_start": event.window_start,
                "window_end": event.window_end,
                "direction": event.direction,
                "declared_by": event.declared_by,
                "declared_on": event.declared_on,
                "triage_state": state,
            }
        )
    events.sort(key=lambda r: (r["commodity"], r["window_start"], r["event_id"]))
    rows["active_events"] = events

    signals: list[dict] = []
    for signal in store.list_buy_signals():
        if signal.as_of > as_of:
            continue
        signals.append(
            {
                "signal_id": signal.signal_id,
                "commodity": signal.commodity,
                "market": signal.market,
                "forecast_id": signal.forecast_id,
                "as_of": signal.as_of,
                "horizon_days": signal.horizon_days,
                "spot_inr": signal.spot_inr,
                "p50_horizon_inr": signal.p50_horizon_inr,
                "drift_pct": signal.drift_pct,
                "band_width_pct": signal.band_width_pct,
                "value": signal.value,
                "accuracy_state": signal.accuracy_state,
            }
        )
    signals.sort(key=lambda r: (r["commodity"], r["market"], r["as_of"], r["signal_id"]))
    rows["buy_signals"] = signals

    return rows


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def render_pdf(lines: list[str]) -> bytes:
    """A deterministic text PDF: Letter pages, Helvetica,
    42 lines a page, no timestamps, no compression."""
    per_page = 42
    pages = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based object number

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    # Page objects are numbered before the Pages object
    # that references them exists, so their bodies are
    # staged and appended once the parent number is
    # known: font, contents and pages take the next
    # numbers in order, then the staged pages, then the
    # catalog.
    content_ids: list[int] = []
    for page in pages:
        stream_lines = ["BT", "/F1 10 Tf", "14 TL", "48 756 Td"]
        for line in page:
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("utf-8")
        content_ids.append(
            add(
                b"<< /Length "
                + str(len(stream)).encode()
                + b" >>\nstream\n"
                + stream
                + b"\nendstream"
            )
        )
    # Object numbers from here: the Pages object is
    # next (len(objects) + 1), the staged page objects
    # follow it in order, the catalog is last.
    pages_id = len(objects) + 1
    kids = " ".join(
        f"{pages_id + 1 + i} 0 R" for i in range(len(pages))
    )
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for content_id in content_ids:
        body = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()
        objects.append(body)
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode())
        out.write(body)
        out.write(b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    return out.getvalue()


def pdf_lines(
    as_of: date,
    pack_version: str,
    section_rows: dict[str, int],
    section_files: list[PackFile],
    rows: dict[str, list[dict]],
) -> list[str]:
    lines = [
        "Verdanta Foods - desk board pack",
        f"as of {as_of.isoformat()}",
        f"integrations pack {pack_version}",
        "",
    ]
    for name, count in section_rows.items():
        lines.append(f"{name}: {count} rows")
    lines.append("")
    lines.append("Official forecast horizon figures (INR/quintal):")
    by_forecast: dict[str, list[dict]] = {}
    for row in rows["official_forecasts"]:
        by_forecast.setdefault(row["forecast_id"], []).append(row)
    for forecast_id, frows in by_forecast.items():
        first = frows[0]
        last = frows[-1]
        lines.append(
            f"  {first['commodity']}/{first['market']} {forecast_id} "
            f"approved by {first['approved_by']} on {first['decided_on']}: "
            f"P50 {fmt(first['p50_inr'])} on {first['forecast_date']} to "
            f"{fmt(last['p50_inr'])} on {last['forecast_date']}"
        )
    lines.append("")
    lines.append("Section files in this pack (see manifest.json for checksums):")
    for file in section_files:
        lines.append(f"  {file.name}  {file.size_bytes} bytes  sha256 {file.sha256[:16]}...")
    return lines


def _pack_file(name: str, media_type: str, data: bytes) -> PackFile:
    return PackFile(
        name=name,
        media_type=media_type,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        content_b64=base64.b64encode(data).decode(),
    )


def build_board_pack(
    store: Store,
    pack: IntegrationsPack,
    as_of: date,
    struck_at: datetime,
) -> BoardPack:
    """The one builder both the synchronous path and the
    job runner call — the same store at the same as-of
    builds the same pack, byte for byte, whenever it
    runs. struck_at is carried onto the artefact as
    metadata only."""
    rows = section_rows(store, pack, as_of)
    section_names = [section.name for section in pack.sections]
    counts = {name: len(rows[name]) for name in section_names}
    files: list[PackFile] = []
    for section in pack.sections:
        text = render_csv(section.columns, rows[section.name])
        files.append(
            _pack_file(f"{section.name}.csv", "text/csv", text.encode("utf-8"))
        )
    pdf = render_pdf(pdf_lines(as_of, pack.version, counts, files, rows))
    files.append(_pack_file("pack.pdf", "application/pdf", pdf))
    board = BoardPack(
        pack_id="BPK-pending",
        as_of=as_of,
        struck_at=struck_at,
        sections=section_names,
        section_rows=counts,
        files=files,
        integrations_pack_version=pack.version,
    )
    # The address covers the as-of, the sections and
    # the files the manifest indexes — not the
    # struck-at, and not the manifest itself, which
    # names the address it cannot be inside (see
    # board_pack_content_id).
    board = board.model_copy(update={"pack_id": board_pack_content_id(board)})
    manifest = {
        "pack_id": board.pack_id,
        "as_of": as_of.isoformat(),
        "integrations_pack_version": pack.version,
        "files": [
            {"name": f.name, "sha256": f.sha256, "size_bytes": f.size_bytes}
            for f in board.files
        ],
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    board.files.append(
        _pack_file("manifest.json", "application/json", manifest_text.encode("utf-8"))
    )
    return board


def file_bytes(file: PackFile) -> bytes:
    return base64.b64decode(file.content_b64.encode())
