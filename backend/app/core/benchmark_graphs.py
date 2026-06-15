from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GraphArtifact:
    report_type: str
    report_id: str
    source_path: str
    output_dir: str
    html_path: str
    svg_paths: list[str]


def render_graphical_reports(report_paths: list[str | Path], *, output_dir: str | Path) -> dict:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[GraphArtifact] = []
    skipped: list[dict[str, str]] = []
    seen_report_ids: set[str] = set()
    for raw_path in report_paths:
        source_path = Path(raw_path)
        try:
            payload = _load_json(source_path)
        except Exception as exc:
            skipped.append({"path": str(source_path), "reason": f"invalid_json: {exc}"})
            continue
        report_type = detect_benchmark_report_type(payload)
        if not report_type:
            skipped.append({"path": str(source_path), "reason": "unsupported_schema"})
            continue
        report_id = str(payload.get("report_id") or source_path.stem)
        if report_id in seen_report_ids:
            skipped.append({"path": str(source_path), "reason": f"duplicate_report_id: {report_id}"})
            continue
        seen_report_ids.add(report_id)
        report_dir = target_dir / _slugify(report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        artifact = _render_report(payload, report_type=report_type, source_path=source_path, output_dir=report_dir)
        artifacts.append(artifact)
    index_path = target_dir / "index.html"
    index_path.write_text(_render_index(artifacts, skipped), encoding="utf-8")
    return {
        "output_dir": str(target_dir),
        "index_path": str(index_path),
        "report_count": len(artifacts),
        "skipped_count": len(skipped),
        "reports": [
            {
                "report_id": item.report_id,
                "report_type": item.report_type,
                "source_path": item.source_path,
                "output_dir": item.output_dir,
                "html_path": item.html_path,
                "svg_paths": item.svg_paths,
            }
            for item in artifacts
        ],
        "skipped": skipped,
    }


def detect_benchmark_report_type(payload: dict) -> str | None:
    report_id = str(payload.get("report_id") or "")
    if report_id.startswith("pdf-benchmark-") or "parser_summaries" in payload:
        return "pdf_parser"
    if report_id.startswith("ingestion-benchmark-") or ("operator_summary" in payload and "product_summary" in payload and "rows" in payload and "suffix" in (payload.get("rows") or [{}])[0]):
        return "ingestion"
    if report_id.startswith("context-strategy-benchmark-") or ("product_summary" in payload and "strategies" in (payload.get("rows") or [{}])[0]):
        return "context_strategy"
    if report_id.startswith("context-layer-report-") or "average_packet_savings_percent" in payload:
        return "context_layer"
    if report_id.startswith("query-benchmark-") or "thresholds" in payload:
        return "retrieval_threshold"
    if "current_architecture" in payload and "turbovec_prototype" in payload:
        return "real_vault_retrieval"
    if "results" in payload and "passed" in payload and "failed" in payload:
        return "release_proof"
    return None


def discover_benchmark_reports(search_roots: list[str | Path]) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for raw_root in search_roots:
        root = Path(raw_root)
        if root.is_file() and root.suffix.lower() == ".json":
            candidate = str(root.resolve())
            if candidate not in seen:
                discovered.append(candidate)
                seen.add(candidate)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            candidate = str(path.resolve())
            if candidate in seen:
                continue
            try:
                payload = _load_json(path)
            except Exception:
                continue
            if detect_benchmark_report_type(payload):
                discovered.append(candidate)
                seen.add(candidate)
    return sorted(discovered)


def _render_report(payload: dict, *, report_type: str, source_path: Path, output_dir: Path) -> GraphArtifact:
    if report_type == "pdf_parser":
        charts, cards = _pdf_parser_charts(payload)
        title = "PDF Parser Benchmark"
    elif report_type == "ingestion":
        charts, cards = _ingestion_charts(payload)
        title = "Ingestion Benchmark"
    elif report_type == "context_strategy":
        charts, cards = _context_strategy_charts(payload)
        title = "Context Strategy Benchmark"
    elif report_type == "context_layer":
        charts, cards = _context_layer_charts(payload)
        title = "Context Layer Benchmark"
    elif report_type == "retrieval_threshold":
        charts, cards = _retrieval_threshold_charts(payload)
        title = "Retrieval Threshold Benchmark"
    elif report_type == "real_vault_retrieval":
        charts, cards = _real_vault_retrieval_charts(payload)
        title = "Real Vault Retrieval Benchmark"
    else:
        charts, cards = _release_proof_charts(payload)
        title = "Release Proof"

    svg_paths: list[str] = []
    chart_blocks: list[str] = []
    for index, chart in enumerate(charts, start=1):
        file_name = f"{index:02d}-{_slugify(chart['title'])}.svg"
        svg_path = output_dir / file_name
        svg_path.write_text(chart["svg"], encoding="utf-8")
        svg_paths.append(str(svg_path))
        chart_blocks.append(
            f"<section class='panel'><h2>{_escape(chart['title'])}</h2><img src='{html.escape(file_name)}' alt='{_escape(chart['title'])}' /></section>"
        )
    raw_json_name = "report.json"
    (output_dir / raw_json_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path = output_dir / "index.html"
    html_path.write_text(
        _report_html(
            title=title,
            payload=payload,
            cards=cards,
            chart_blocks=chart_blocks,
            source_path=str(source_path),
        ),
        encoding="utf-8",
    )
    return GraphArtifact(
        report_type=report_type,
        report_id=str(payload.get("report_id") or source_path.stem),
        source_path=str(source_path),
        output_dir=str(output_dir),
        html_path=str(html_path),
        svg_paths=svg_paths,
    )


def _pdf_parser_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    summaries = payload.get("parser_summaries") or {}
    items = sorted(summaries.values(), key=lambda item: str(item.get("parser") or ""))
    cards = [
        ("Reports", str(len(items))),
        ("Selected Backend", str((payload.get("runtime") or {}).get("selected_backend") or "unknown")),
        ("Rows", str(len(payload.get("rows") or []))),
    ]
    charts = [
        _bar_chart(
            "Average Seconds Per Document",
            [(str(item.get("parser") or "unknown"), float(item.get("avg_seconds_per_document") or 0.0)) for item in items],
            unit="s",
        ),
        _bar_chart(
            "Parser Success Rate",
            [
                (
                    str(item.get("parser") or "unknown"),
                    round((float(item.get("success_count") or 0.0) / max(float(item.get("document_count") or 0.0), 1.0)) * 100.0, 2),
                )
                for item in items
            ],
            unit="%",
            max_value=100.0,
        ),
        _bar_chart(
            "Average Text Characters Per Document",
            [(str(item.get("parser") or "unknown"), float(item.get("avg_chars_per_document") or 0.0)) for item in items],
            unit=" chars",
        ),
    ]
    return charts, cards


def _ingestion_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    rows = payload.get("rows") or []
    type_breakdown = ((payload.get("operator_summary") or {}).get("type_breakdown") or {})
    cards = [
        ("Documents", str((payload.get("operator_summary") or {}).get("document_count") or len(rows))),
        ("Success Rate", f"{float((payload.get('product_summary') or {}).get('import_success_rate_percent') or 0.0):.2f}%"),
        ("Median Latency", f"{float((payload.get('product_summary') or {}).get('median_document_latency_seconds') or 0.0):.4f}s"),
    ]
    charts = [
        _bar_chart(
            "Per-Document Ingestion Latency",
            [(Path(str(row.get("path") or "")).name or f"doc-{index+1}", float(row.get("seconds") or 0.0)) for index, row in enumerate(rows[:20])],
            unit="s",
        ),
        _bar_chart(
            "Average Latency By File Type",
            [(suffix, float(item.get("avg_seconds_per_document") or 0.0)) for suffix, item in sorted(type_breakdown.items())],
            unit="s",
        ),
        _bar_chart(
            "Extracted Text Size By File Type",
            [(suffix, float(item.get("text_chars") or 0.0)) for suffix, item in sorted(type_breakdown.items())],
            unit=" chars",
        ),
    ]
    return charts, cards


def _context_strategy_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    rows = payload.get("rows") or []
    strategies = ["current_cml", "context_caching_warm", "mem_u_style", "context_mode_style"]
    labels = {
        "current_cml": "Current CML",
        "context_caching_warm": "Context Caching Warm",
        "mem_u_style": "Mem-U Style",
        "context_mode_style": "Context Mode Style",
    }
    avg_values = []
    for key in strategies:
        values = []
        for row in rows:
            row_strategies = row.get("strategies") or {}
            if key == "context_caching_warm":
                values.append(float(((row_strategies.get("context_caching") or {}).get("warm_reduction_percent") or 0.0)))
            else:
                values.append(float(((row_strategies.get(key) or {}).get("reduction_percent") or 0.0)))
        avg_values.append((labels[key], round(sum(values) / max(len(values), 1), 2)))
    cards = [
        ("Queries", str(payload.get("query_count") or len(rows))),
        ("Best Avg Strategy", str((payload.get("product_summary") or {}).get("best_average_strategy") or "unknown")),
        ("Warm Cache Avg", f"{float((payload.get('product_summary') or {}).get('warm_cache_average_reduction_percent') or 0.0):.2f}%"),
    ]
    charts = [
        _bar_chart("Average Token Reduction By Strategy", avg_values, unit="%", max_value=100.0),
        _grouped_bar_chart(
            "Per-Query Strategy Reduction",
            [str(row.get("query") or f"query-{index+1}") for index, row in enumerate(rows)],
            [
                ("Current CML", [float(((row.get("strategies") or {}).get("current_cml") or {}).get("reduction_percent") or 0.0) for row in rows]),
                ("Cache Warm", [float(((row.get("strategies") or {}).get("context_caching") or {}).get("warm_reduction_percent") or 0.0) for row in rows]),
                ("Mem-U", [float(((row.get("strategies") or {}).get("mem_u_style") or {}).get("reduction_percent") or 0.0) for row in rows]),
                ("Context Mode", [float(((row.get("strategies") or {}).get("context_mode_style") or {}).get("reduction_percent") or 0.0) for row in rows]),
            ],
            unit="%",
            max_value=100.0,
        ),
        _grouped_bar_chart(
            "Raw Vs Current Tokens",
            [str(row.get("query") or f"query-{index+1}") for index, row in enumerate(rows)],
            [
                ("Raw", [float(row.get("raw_tokens") or 0.0) for row in rows]),
                ("Current CML", [float(row.get("current_cml_tokens") or 0.0) for row in rows]),
                ("Cache Warm", [float(((row.get("strategies") or {}).get("context_caching") or {}).get("warm_tokens") or 0.0) for row in rows]),
            ],
            unit=" tokens",
        ),
    ]
    return charts, cards


def _context_layer_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    rows = payload.get("rows") or []
    cards = [
        ("Queries", str(payload.get("query_count") or len(rows))),
        ("Avg Packet Savings", f"{float(payload.get('average_packet_savings_percent') or 0.0):.2f}%"),
        ("Degraded Queries", str(payload.get("degraded_query_count") or 0)),
    ]
    charts = [
        _bar_chart(
            "Packet Savings By Query",
            [(str(row.get("query") or f"query-{index+1}"), float(row.get("packet_savings_percent") or 0.0)) for index, row in enumerate(rows)],
            unit="%",
            max_value=100.0,
        ),
        _grouped_bar_chart(
            "Raw Vs Packet Bytes",
            [str(row.get("query") or f"query-{index+1}") for index, row in enumerate(rows)],
            [
                ("Raw Payload", [float(row.get("raw_payload_bytes") or 0.0) for row in rows]),
                ("Packet", [float(row.get("packet_bytes") or 0.0) for row in rows]),
            ],
            unit=" bytes",
        ),
        _bar_chart(
            "Expansion Handles Per Query",
            [(str(row.get("query") or f"query-{index+1}"), float(row.get("expansion_handle_count") or 0.0)) for index, row in enumerate(rows)],
            unit=" handles",
        ),
    ]
    return charts, cards


def _retrieval_threshold_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    rows = payload.get("rows") or []
    thresholds = [str(item) for item in payload.get("thresholds") or []]
    pass_rates = []
    chunk_means = []
    for threshold in payload.get("thresholds") or []:
        threshold_rows = [row for row in rows if float(row.get("threshold") or 0.0) == float(threshold)]
        pass_rates.append(
            (
                str(threshold),
                round((sum(1 for row in threshold_rows if row.get("passes_fixture")) / max(len(threshold_rows), 1)) * 100.0, 2),
            )
        )
        chunk_means.append(
            (
                str(threshold),
                round(sum(float(row.get("chunks_passing") or 0.0) for row in threshold_rows) / max(len(threshold_rows), 1), 2),
            )
        )
    cards = [
        ("Fixtures", str(payload.get("fixture_count") or 0)),
        ("Thresholds", str(len(thresholds))),
        ("Rows", str(len(rows))),
    ]
    charts = [
        _bar_chart("Fixture Pass Rate By Threshold", pass_rates, unit="%", max_value=100.0),
        _bar_chart("Average Chunks Passing By Threshold", chunk_means, unit=" chunks"),
    ]
    return charts, cards


def _real_vault_retrieval_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    current = payload.get("current_architecture") or {}
    turbovec = payload.get("turbovec_prototype") or {}
    overlap = payload.get("overlap") or {}
    cards = [
        ("PDFs", str(payload.get("discovered_pdf_count") or 0)),
        ("Total Runtime", f"{float(payload.get('total_seconds') or 0.0):.2f}s"),
        ("Overlap Avg", f"{float(overlap.get('average_overlap_percent') or 0.0):.2f}%"),
    ]
    charts = [
        _bar_chart(
            "Search Latency Avg",
            [
                ("Current", float(((current.get("search_latency_ms") or {}).get("avg")) or 0.0)),
                ("Turbovec", float(((turbovec.get("search_latency_ms") or {}).get("avg")) or 0.0)),
            ],
            unit=" ms",
        ),
        _bar_chart(
            "Total Latency Avg",
            [
                ("Current", float(((current.get("total_latency_ms") or {}).get("avg")) or 0.0)),
                ("Turbovec", float(((turbovec.get("total_latency_ms") or {}).get("avg")) or 0.0)),
            ],
            unit=" ms",
        ),
        _bar_chart(
            "Pipeline Runtime Breakdown",
            [
                ("Warmup", float(payload.get("embedding_warmup") or 0.0)),
                ("Ingest", float((payload.get("ingest") or {}).get("seconds") or 0.0)),
                ("Reindex", float((payload.get("reindex") or {}).get("seconds") or 0.0)),
                ("Total", float(payload.get("total_seconds") or 0.0)),
            ],
            unit="s",
        ),
    ]
    return charts, cards


def _release_proof_charts(payload: dict) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    results = payload.get("results") or []
    cards = [
        ("Passed", str(payload.get("passed") or 0)),
        ("Failed", str(payload.get("failed") or 0)),
        ("Checks", str(len(results))),
    ]
    charts = [
        _bar_chart(
            "Release Proof Status Counts",
            [("Passed", float(payload.get("passed") or 0.0)), ("Failed", float(payload.get("failed") or 0.0))],
            unit=" checks",
        ),
        _bar_chart(
            "Checks By Result",
            [(str(item.get("name") or f"check-{index+1}"), 1.0 if item.get("status") == "passed" else 0.0) for index, item in enumerate(results)],
            unit=" pass",
            max_value=1.0,
        ),
    ]
    return charts, cards


def _report_html(*, title: str, payload: dict, cards: list[tuple[str, str]], chart_blocks: list[str], source_path: str) -> str:
    card_html = "".join(
        f"<div class='card'><div class='label'>{_escape(label)}</div><div class='value'>{_escape(value)}</div></div>"
        for label, value in cards
    )
    facts = [
        ("Report ID", str(payload.get("report_id") or "")),
        ("Generated At", str(payload.get("generated_at") or "")),
        ("Source JSON", source_path),
    ]
    fact_html = "".join(f"<tr><th>{_escape(label)}</th><td>{_escape(value)}</td></tr>" for label, value in facts if value)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{_escape(title)}</title>
  <style>
    body {{ font-family: "Segoe UI", sans-serif; margin: 0; background: #f4f1ea; color: #1f2937; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 32px; }}
    h1 {{ margin: 0 0 8px; font-size: 32px; }}
    p.meta {{ color: #5b6472; margin: 0 0 24px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 24px 0; }}
    .card, .panel {{ background: #fffdf7; border: 1px solid #ddd4c6; border-radius: 16px; box-shadow: 0 10px 30px rgba(58, 52, 46, 0.06); }}
    .card {{ padding: 18px; }}
    .label {{ color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }}
    .value {{ font-size: 28px; margin-top: 10px; font-weight: 700; }}
    .facts {{ width: 100%; border-collapse: collapse; }}
    .facts th, .facts td {{ text-align: left; padding: 12px 0; border-bottom: 1px solid #ebe4d8; vertical-align: top; }}
    .facts th {{ width: 160px; color: #6b7280; }}
    .grid {{ display: grid; gap: 20px; }}
    .panel {{ padding: 18px; }}
    .panel h2 {{ margin: 0 0 14px; font-size: 20px; }}
    .panel img {{ width: 100%; height: auto; display: block; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; color: #374151; }}
  </style>
</head>
<body>
  <main>
    <h1>{_escape(title)}</h1>
    <p class="meta">{_escape(str(payload.get("generated_at") or ""))}</p>
    <div class="cards">{card_html}</div>
    <section class="panel"><h2>Report Facts</h2><table class="facts">{fact_html}</table></section>
    <div class="grid">{''.join(chart_blocks)}</div>
  </main>
</body>
</html>
"""


def _render_index(artifacts: list[GraphArtifact], skipped: list[dict[str, str]]) -> str:
    items = []
    for item in artifacts:
        rel = f"{Path(item.output_dir).name}/index.html"
        items.append(
            f"<tr><td><a href='{html.escape(rel)}'>{_escape(item.report_id)}</a></td><td>{_escape(item.report_type)}</td><td>{_escape(item.source_path)}</td><td>{len(item.svg_paths)}</td></tr>"
        )
    skipped_rows = "".join(
        f"<tr><td>{_escape(row['path'])}</td><td>{_escape(row['reason'])}</td></tr>"
        for row in skipped
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Benchmark Graph Reports</title>
  <style>
    body {{ font-family: "Segoe UI", sans-serif; margin: 0; background: #eef3ef; color: #1f2937; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 32px; }}
    h1 {{ margin: 0 0 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #dbe3dc; border-radius: 14px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 12px 14px; border-bottom: 1px solid #e5ece6; vertical-align: top; }}
    th {{ background: #f8fbf9; color: #5f6b63; }}
    section {{ margin-top: 24px; }}
  </style>
</head>
<body>
  <main>
    <h1>Benchmark Graph Reports</h1>
    <p>Rendered {len(artifacts)} supported reports.</p>
    <section>
      <table>
        <thead><tr><th>Report</th><th>Type</th><th>Source</th><th>Charts</th></tr></thead>
        <tbody>{''.join(items) or '<tr><td colspan="4">No reports rendered.</td></tr>'}</tbody>
      </table>
    </section>
    <section>
      <h2>Skipped Files</h2>
      <table>
        <thead><tr><th>Path</th><th>Reason</th></tr></thead>
        <tbody>{skipped_rows or '<tr><td colspan="2">None.</td></tr>'}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _bar_chart(title: str, points: list[tuple[str, float]], *, unit: str = "", max_value: float | None = None) -> dict[str, str]:
    labels = [label for label, _ in points]
    values = [float(value) for _, value in points]
    return {"title": title, "svg": _build_svg_chart(labels, [("Series", values)], unit=unit, max_value=max_value)}


def _grouped_bar_chart(
    title: str,
    labels: list[str],
    series: list[tuple[str, list[float]]],
    *,
    unit: str = "",
    max_value: float | None = None,
) -> dict[str, str]:
    return {"title": title, "svg": _build_svg_chart(labels, series, unit=unit, max_value=max_value)}


def _build_svg_chart(labels: list[str], series: list[tuple[str, list[float]]], *, unit: str, max_value: float | None) -> str:
    width = 1120
    height = max(420, 220 + (len(labels) * 28))
    margin_left = 220
    margin_right = 40
    margin_top = 50
    margin_bottom = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    flattened = [max(0.0, float(value)) for _, values in series for value in values]
    scale_max = float(max_value if max_value is not None else max(flattened or [1.0]))
    if scale_max <= 0:
        scale_max = 1.0
    series_count = max(len(series), 1)
    row_height = plot_height / max(len(labels), 1)
    bar_height = min(20.0, (row_height - 8.0) / series_count)
    colors = ["#1d4ed8", "#0f766e", "#b45309", "#b91c1c", "#7c3aed"]
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<rect width='100%' height='100%' fill='#fffdf7' />",
    ]
    for tick in range(6):
        x = margin_left + (plot_width * tick / 5.0)
        value = scale_max * tick / 5.0
        parts.append(f"<line x1='{x:.2f}' y1='{margin_top}' x2='{x:.2f}' y2='{height - margin_bottom}' stroke='#ebe4d8' stroke-width='1' />")
        parts.append(f"<text x='{x:.2f}' y='28' font-size='12' fill='#6b7280' text-anchor='middle'>{_escape(_format_number(value, unit))}</text>")
    for label_index, label in enumerate(labels):
        y_top = margin_top + (label_index * row_height)
        parts.append(
            f"<text x='{margin_left - 12}' y='{(y_top + row_height / 2.0 + 5):.2f}' font-size='13' fill='#1f2937' text-anchor='end'>{_escape(_truncate(label, 32))}</text>"
        )
        for series_index, (_, values) in enumerate(series):
            value = max(0.0, float(values[label_index] if label_index < len(values) else 0.0))
            bar_y = y_top + 4 + (series_index * bar_height)
            bar_width = (value / scale_max) * plot_width
            color = colors[series_index % len(colors)]
            parts.append(
                f"<rect x='{margin_left}' y='{bar_y:.2f}' width='{bar_width:.2f}' height='{max(bar_height - 2.0, 4.0):.2f}' rx='5' fill='{color}' opacity='0.9' />"
            )
            parts.append(
                f"<text x='{min(margin_left + bar_width + 8, width - margin_right):.2f}' y='{(bar_y + bar_height - 4):.2f}' font-size='12' fill='#374151'>{_escape(_format_number(value, unit))}</text>"
            )
    legend_x = margin_left
    legend_y = height - 12
    for series_index, (name, _) in enumerate(series):
        color = colors[series_index % len(colors)]
        x = legend_x + (series_index * 180)
        parts.append(f"<rect x='{x}' y='{legend_y - 12}' width='14' height='14' rx='3' fill='{color}' />")
        parts.append(f"<text x='{x + 22}' y='{legend_y}' font-size='12' fill='#4b5563'>{_escape(name)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _format_number(value: float, unit: str) -> str:
    if unit.strip() == "%":
        return f"{value:.2f}%"
    if math.isfinite(value) and value >= 1000:
        return f"{value:,.0f}{unit}"
    if math.isfinite(value) and value >= 100:
        return f"{value:.1f}{unit}"
    if math.isfinite(value) and value >= 10:
        return f"{value:.2f}{unit}"
    return f"{value:.4f}{unit}"


def _escape(value: str) -> str:
    return html.escape(str(value))


def _slugify(value: str) -> str:
    collapsed = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return collapsed or "report"


def _truncate(value: str, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))
