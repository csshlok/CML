import argparse
import csv
import json
import sys
from pathlib import Path


SVG_WIDTH = 1000
SVG_HEIGHT = 560


def main() -> None:
    parser = argparse.ArgumentParser(description="Export summary artifacts for a LoRA benchmark run.")
    parser.add_argument("--benchmark", required=True, help="Path to post-training-benchmark.json")
    parser.add_argument("--trainer-state", required=True, help="Path to trainer_state.json")
    parser.add_argument("--output-prefix", required=True, help="Output prefix, e.g. .tmp/run-name")
    args = parser.parse_args()

    benchmark_path = Path(args.benchmark)
    trainer_state_path = Path(args.trainer_state)
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    benchmark_payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
    trainer_state = json.loads(trainer_state_path.read_text(encoding="utf-8"))

    metrics = dict(benchmark_payload.get("metrics") or {})
    benchmark_report = dict(metrics.get("benchmark_report") or {})
    overall = dict(benchmark_report.get("overall") or {})
    graduation = dict(benchmark_report.get("graduation_overall") or {})
    bundle_summary = dict(benchmark_report.get("bundle_benchmark_summary") or {})
    category_scores = dict(benchmark_report.get("category_scores") or {})
    bundle_category_scores = dict(benchmark_report.get("bundle_category_scores") or {})
    gate_report = dict(benchmark_report.get("bundle_release_gate") or benchmark_report.get("gate_report") or {})
    benchmark_modes = dict(benchmark_report.get("bundle_benchmark_modes") or benchmark_report.get("benchmark_modes") or {})
    mode_case_outputs = dict(benchmark_report.get("bundle_case_outputs") or benchmark_report.get("mode_case_outputs") or {})
    retrieval_case_scores = list(metrics.get("retrieval_case_scores") or [])
    adapter_case_scores = list(metrics.get("adapter_case_scores") or [])
    quality_gate = dict(metrics.get("quality_gate") or {})

    eval_curve = [
        {
            "step": int(item.get("step") or 0),
            "epoch": float(item.get("epoch") or 0.0),
            "eval_loss": float(item.get("eval_loss") or 0.0),
            "eval_runtime": float(item.get("eval_runtime") or 0.0),
        }
        for item in trainer_state.get("log_history", [])
        if isinstance(item, dict) and "eval_loss" in item
    ]

    summary = {
        "adapter_dir": benchmark_payload.get("adapter_path"),
        "base_model": benchmark_payload.get("base_model"),
        "dataset_hash": benchmark_payload.get("dataset_hash"),
        "created_at": benchmark_payload.get("created_at"),
        "status": benchmark_payload.get("status"),
        "passes": benchmark_payload.get("passes"),
        "compatibility_only": {
            "legacy_category_scores": True,
            "legacy_graduation_overall": True,
            "legacy_overall_adapter_labels": True,
        },
        "quality_gate": quality_gate,
        "bundle_gate": gate_report,
        "bundle_benchmark_summary": bundle_summary,
        "benchmark_modes": benchmark_modes,
        "overall": overall,
        "graduation_overall": graduation,
        "best_metric": trainer_state.get("best_metric"),
        "best_global_step": trainer_state.get("best_global_step"),
        "best_model_checkpoint": trainer_state.get("best_model_checkpoint"),
        "global_step": trainer_state.get("global_step"),
        "epoch": trainer_state.get("epoch"),
        "eval_points": len(eval_curve),
        "category_count": len(category_scores),
        "bundle_mode_count": len(benchmark_modes),
        "case_count": benchmark_report.get("case_count"),
        "scored_case_count": benchmark_report.get("scored_case_count"),
        "evaluation_plan_case_count": ((metrics.get("evaluation_plan") or {}).get("case_count")),
        "eval_curve": eval_curve,
    }

    summary_path = output_prefix.with_name(output_prefix.name + "-summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    eval_csv_path = output_prefix.with_name(output_prefix.name + "-eval-curve.csv")
    with eval_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["step", "epoch", "eval_loss", "eval_runtime"])
        writer.writeheader()
        writer.writerows(eval_curve)

    category_csv_path = output_prefix.with_name(output_prefix.name + "-legacy-category-scores.csv")
    with category_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "category",
                "owner",
                "counts_toward_graduation",
                "case_count",
                "retrieval_only_score",
                "adapter_score",
                "quality_delta",
                "passes",
            ],
        )
        writer.writeheader()
        for category, report in category_scores.items():
            writer.writerow(
                {
                    "category": category,
                    "owner": report.get("owner"),
                    "counts_toward_graduation": report.get("counts_toward_graduation"),
                    "case_count": report.get("case_count"),
                    "retrieval_only_score": report.get("retrieval_only_score"),
                    "adapter_score": report.get("adapter_score"),
                    "quality_delta": report.get("quality_delta"),
                    "passes": report.get("passes"),
                }
            )

    bundle_category_csv_path = output_prefix.with_name(output_prefix.name + "-bundle-category-scores.csv")
    with bundle_category_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "category",
                "owner",
                "counts_toward_graduation",
                "case_count",
                "meaningful_case_count_reached",
                "complete",
                "retrieval_only_full_score",
                "retrieval_only_small_score",
                "bundle_with_expert_score",
                "bundle_without_expert_score",
                "retrieval_only_full_tokens",
                "retrieval_only_small_tokens",
                "bundle_with_expert_tokens",
                "bundle_without_expert_tokens",
                "quality_regression_vs_retrieval_full",
                "quality_gain_vs_retrieval_small",
                "token_savings_vs_retrieval_full",
                "unsupported_claim_rate",
                "wrong_citation_rate",
            ],
        )
        writer.writeheader()
        for category, report in bundle_category_scores.items():
            retrieval_full = dict(report.get("retrieval_only_full") or {})
            retrieval_small = dict(report.get("retrieval_only_small") or {})
            bundle_with_expert = dict(report.get("bundle_with_expert") or {})
            bundle_without_expert = dict(report.get("bundle_without_expert") or {})
            writer.writerow(
                {
                    "category": category,
                    "owner": report.get("owner"),
                    "counts_toward_graduation": report.get("counts_toward_graduation"),
                    "case_count": report.get("case_count"),
                    "meaningful_case_count_reached": report.get("meaningful_case_count_reached"),
                    "complete": report.get("complete"),
                    "retrieval_only_full_score": retrieval_full.get("score"),
                    "retrieval_only_small_score": retrieval_small.get("score"),
                    "bundle_with_expert_score": bundle_with_expert.get("score"),
                    "bundle_without_expert_score": bundle_without_expert.get("score"),
                    "retrieval_only_full_tokens": retrieval_full.get("token_count"),
                    "retrieval_only_small_tokens": retrieval_small.get("token_count"),
                    "bundle_with_expert_tokens": bundle_with_expert.get("token_count"),
                    "bundle_without_expert_tokens": bundle_without_expert.get("token_count"),
                    "quality_regression_vs_retrieval_full": report.get("quality_regression_vs_retrieval_full"),
                    "quality_gain_vs_retrieval_small": report.get("quality_gain_vs_retrieval_small"),
                    "token_savings_vs_retrieval_full": report.get("token_savings_vs_retrieval_full"),
                    "unsupported_claim_rate": bundle_with_expert.get("unsupported_claim_rate"),
                    "wrong_citation_rate": bundle_with_expert.get("wrong_citation_rate"),
                }
            )

    modes_csv_path = output_prefix.with_name(output_prefix.name + "-bundle-modes.csv")
    with modes_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "mode",
                "score",
                "token_count",
                "latency_ms",
                "unsupported_claim_rate",
                "wrong_citation_rate",
            ],
        )
        writer.writeheader()
        for mode_name, report in benchmark_modes.items():
            writer.writerow(
                {
                    "mode": mode_name,
                    "score": report.get("score"),
                    "token_count": report.get("token_count"),
                    "latency_ms": report.get("latency_ms"),
                    "unsupported_claim_rate": report.get("unsupported_claim_rate"),
                    "wrong_citation_rate": report.get("wrong_citation_rate"),
                }
            )

    case_csv_path = output_prefix.with_name(output_prefix.name + "-legacy-case-scores.csv")
    adapter_by_case = {item.get("case_id"): item for item in adapter_case_scores}
    with case_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "category",
                "owner",
                "counts_toward_graduation",
                "retrieval_score",
                "adapter_score",
                "score_delta",
            ],
        )
        writer.writeheader()
        for item in retrieval_case_scores:
            case_id = item.get("case_id")
            adapter_item = adapter_by_case.get(case_id) or {}
            retrieval_score = float(item.get("score") or 0.0)
            adapter_score = float(adapter_item.get("score") or 0.0)
            writer.writerow(
                {
                    "case_id": case_id,
                    "category": item.get("category"),
                    "owner": item.get("owner"),
                    "counts_toward_graduation": item.get("counts_toward_graduation"),
                    "retrieval_score": retrieval_score,
                    "adapter_score": adapter_score,
                    "score_delta": round(adapter_score - retrieval_score, 2),
                }
            )

    bundle_case_csv_path = output_prefix.with_name(output_prefix.name + "-bundle-case-outputs.csv")
    with bundle_case_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "mode",
                "case_id",
                "category",
                "source_title",
                "expert_used",
                "score",
                "grounding_consistency_score",
                "citation_present",
                "retrieval_hits",
                "prompt_tokens_estimate",
                "retrieval_evidence_tokens_estimate",
                "response_tokens_estimate",
                "packet_tokens_estimate",
                "total_tokens_estimate",
                "raw_packet_text",
                "adapter_prompt",
                "adapter_raw_output",
            ],
        )
        writer.writeheader()
        for mode_name, rows in mode_case_outputs.items():
            for row in list(rows or []):
                token_ledger = dict(row.get("token_ledger") or {})
                writer.writerow(
                    {
                        "mode": mode_name,
                        "case_id": row.get("case_id"),
                        "category": row.get("category"),
                        "source_title": row.get("source_title"),
                        "expert_used": row.get("expert_used"),
                        "score": row.get("score"),
                        "grounding_consistency_score": row.get("grounding_consistency_score"),
                        "citation_present": row.get("citation_present"),
                        "retrieval_hits": row.get("retrieval_hits"),
                        "prompt_tokens_estimate": token_ledger.get("prompt_tokens_estimate"),
                        "retrieval_evidence_tokens_estimate": token_ledger.get("retrieval_evidence_tokens_estimate"),
                        "response_tokens_estimate": token_ledger.get("response_tokens_estimate"),
                        "packet_tokens_estimate": token_ledger.get("packet_tokens_estimate"),
                        "total_tokens_estimate": token_ledger.get("total_tokens_estimate"),
                        "raw_packet_text": row.get("raw_packet_text"),
                        "adapter_prompt": row.get("adapter_prompt"),
                        "adapter_raw_output": row.get("adapter_raw_output"),
                    }
                )

    mode_case_json_path = output_prefix.with_name(output_prefix.name + "-mode-case-outputs.json")
    mode_case_json_path.write_text(json.dumps(mode_case_outputs, indent=2), encoding="utf-8")

    overall_svg_path = output_prefix.with_name(output_prefix.name + "-overall.svg")
    overall_svg_path.write_text(
        _overall_svg(
            retrieval_full=float(bundle_summary.get("retrieval_only_full_score") or overall.get("retrieval_only_score") or 0.0),
            retrieval_small=float(bundle_summary.get("retrieval_only_small_score") or 0.0),
            bundle_with_expert=float(bundle_summary.get("bundle_with_expert_score") or overall.get("adapter_score") or 0.0),
            bundle_without_expert=float(bundle_summary.get("bundle_without_expert_score") or 0.0),
        ),
        encoding="utf-8",
    )

    category_svg_path = output_prefix.with_name(output_prefix.name + "-legacy-category-deltas.svg")
    category_svg_path.write_text(
        _category_delta_svg(
            [
                (
                    category,
                    float(report.get("quality_delta") or 0.0),
                    bool(report.get("counts_toward_graduation")),
                )
                for category, report in category_scores.items()
            ]
        ),
        encoding="utf-8",
    )

    eval_svg_path = output_prefix.with_name(output_prefix.name + "-eval-loss.svg")
    eval_svg_path.write_text(_eval_curve_svg(eval_curve), encoding="utf-8")

    html_path = output_prefix.with_name(output_prefix.name + "-index.html")
    html_path.write_text(
        _index_html(
            summary_path=summary_path.name,
            eval_csv_path=eval_csv_path.name,
            category_csv_path=category_csv_path.name,
            bundle_category_csv_path=bundle_category_csv_path.name,
            case_csv_path=case_csv_path.name,
            bundle_case_csv_path=bundle_case_csv_path.name,
            modes_csv_path=modes_csv_path.name,
            overall_svg_path=overall_svg_path.name,
            category_svg_path=category_svg_path.name,
            eval_svg_path=eval_svg_path.name,
            bundle_summary=bundle_summary,
            overall=overall,
            graduation=graduation,
            gate_report=gate_report,
            best_metric=trainer_state.get("best_metric"),
            best_model_checkpoint=trainer_state.get("best_model_checkpoint"),
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "summary": str(summary_path),
                "eval_curve_csv": str(eval_csv_path),
                "category_scores_csv": str(category_csv_path),
                "bundle_category_scores_csv": str(bundle_category_csv_path),
                "case_scores_csv": str(case_csv_path),
                "bundle_case_outputs_csv": str(bundle_case_csv_path),
                "bundle_modes_csv": str(modes_csv_path),
                "mode_case_outputs_json": str(mode_case_json_path),
                "overall_svg": str(overall_svg_path),
                "category_deltas_svg": str(category_svg_path),
                "eval_loss_svg": str(eval_svg_path),
                "index_html": str(html_path),
            },
            indent=2,
        )
    )


def _overall_svg(*, retrieval_full: float, retrieval_small: float, bundle_with_expert: float, bundle_without_expert: float) -> str:
    series = [
        ("Retrieval Full", retrieval_full, "#1f77b4"),
        ("Retrieval Small", retrieval_small, "#4c78a8"),
        ("Bundle With Expert", bundle_with_expert, "#d62728"),
        ("Bundle Without Expert", bundle_without_expert, "#e15759"),
    ]
    return _bar_chart_svg("Bundle Benchmark Scores", series, max_value=100.0, unit="")


def _category_delta_svg(rows: list[tuple[str, float, bool]]) -> str:
    width = 1100
    height = max(420, 90 + (len(rows) * 48))
    margin_left = 280
    margin_right = 60
    margin_top = 60
    margin_bottom = 50
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    min_value = min([value for _, value, _ in rows] + [0.0, -20.0])
    max_value = max([value for _, value, _ in rows] + [0.0, 20.0])
    scale = max_value - min_value or 1.0
    zero_x = margin_left + ((0 - min_value) / scale) * plot_width
    row_height = plot_height / max(len(rows), 1)
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#111} .small{font-size:12px;fill:#444} .title{font-size:24px;font-weight:600} .label{font-size:14px} .tick{stroke:#d0d0d0;stroke-width:1} .zero{stroke:#222;stroke-width:2}</style>",
        f"<text x='{margin_left}' y='34' class='title'>Category Quality Deltas</text>",
        f"<line x1='{zero_x:.2f}' y1='{margin_top}' x2='{zero_x:.2f}' y2='{height - margin_bottom}' class='zero' />",
    ]
    for tick in range(int(min_value // 5) * 5, int(max_value // 5) * 5 + 6, 5):
        x = margin_left + ((tick - min_value) / scale) * plot_width
        parts.append(f"<line x1='{x:.2f}' y1='{margin_top}' x2='{x:.2f}' y2='{height - margin_bottom}' class='tick' />")
        parts.append(f"<text x='{x:.2f}' y='{height - 18}' text-anchor='middle' class='small'>{tick}</text>")
    for index, (label, value, counts) in enumerate(rows):
        y = margin_top + (index * row_height) + 8
        bar_y = y + 8
        bar_h = max(18.0, row_height * 0.55)
        x1 = zero_x
        x2 = margin_left + ((value - min_value) / scale) * plot_width
        bar_x = min(x1, x2)
        bar_w = abs(x2 - x1)
        color = "#2ca02c" if value >= 0 else "#d62728"
        if counts:
            color = "#1f77b4" if value >= 0 else "#9467bd"
        parts.append(f"<text x='{margin_left - 12}' y='{bar_y + bar_h * 0.75:.2f}' text-anchor='end' class='label'>{_esc(label)}</text>")
        parts.append(f"<rect x='{bar_x:.2f}' y='{bar_y:.2f}' width='{max(bar_w,1):.2f}' height='{bar_h:.2f}' rx='4' fill='{color}' />")
        text_anchor = "start" if value >= 0 else "end"
        text_x = x2 + 8 if value >= 0 else x2 - 8
        parts.append(f"<text x='{text_x:.2f}' y='{bar_y + bar_h * 0.75:.2f}' text-anchor='{text_anchor}' class='small'>{value:.2f}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _eval_curve_svg(eval_curve: list[dict]) -> str:
    width = SVG_WIDTH
    height = SVG_HEIGHT
    margin_left = 80
    margin_right = 40
    margin_top = 60
    margin_bottom = 60
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    values = [float(item["eval_loss"]) for item in eval_curve] or [0.0]
    min_value = min(values)
    max_value = max(values)
    if max_value == min_value:
        max_value += 1.0
    points = []
    for index, item in enumerate(eval_curve):
        x = margin_left + (plot_width * index / max(len(eval_curve) - 1, 1))
        y = margin_top + ((max_value - float(item["eval_loss"])) / (max_value - min_value)) * plot_height
        points.append((x, y, item))
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y, _ in points)
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#111}.small{font-size:12px;fill:#444}.title{font-size:24px;font-weight:600}.axis{stroke:#666;stroke-width:1}.line{fill:none;stroke:#1f77b4;stroke-width:3}</style>",
        f"<text x='{margin_left}' y='34' class='title'>Validation Loss Curve</text>",
        f"<line x1='{margin_left}' y1='{height-margin_bottom}' x2='{width-margin_right}' y2='{height-margin_bottom}' class='axis' />",
        f"<line x1='{margin_left}' y1='{margin_top}' x2='{margin_left}' y2='{height-margin_bottom}' class='axis' />",
        f"<polyline points='{polyline}' class='line' />",
    ]
    for x, y, item in points:
        parts.append(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4' fill='#d62728' />")
        parts.append(f"<text x='{x:.2f}' y='{height - 24}' text-anchor='middle' class='small'>s{int(item['step'])}</text>")
        parts.append(f"<text x='{x:.2f}' y='{y - 10:.2f}' text-anchor='middle' class='small'>{float(item['eval_loss']):.4f}</text>")
    parts.append(f"<text x='{width/2:.2f}' y='{height - 8}' text-anchor='middle' class='small'>Evaluation step</text>")
    parts.append(f"<text x='20' y='{height/2:.2f}' transform='rotate(-90 20,{height/2:.2f})' text-anchor='middle' class='small'>Eval loss</text>")
    parts.append("</svg>")
    return "".join(parts)


def _bar_chart_svg(title: str, rows: list[tuple[str, float, str]], *, max_value: float, unit: str) -> str:
    width = SVG_WIDTH
    height = SVG_HEIGHT
    margin_left = 230
    margin_right = 60
    margin_top = 60
    margin_bottom = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    row_height = plot_height / max(len(rows), 1)
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#111}.small{font-size:12px;fill:#444}.title{font-size:24px;font-weight:600}.tick{stroke:#d0d0d0;stroke-width:1}.label{font-size:14px}</style>",
        f"<text x='{margin_left}' y='34' class='title'>{_esc(title)}</text>",
    ]
    for tick in range(0, 6):
        x = margin_left + (plot_width * tick / 5.0)
        parts.append(f"<line x1='{x:.2f}' y1='{margin_top}' x2='{x:.2f}' y2='{height-margin_bottom}' class='tick' />")
        parts.append(f"<text x='{x:.2f}' y='{height - 12}' text-anchor='middle' class='small'>{(max_value * tick / 5.0):.0f}</text>")
    for index, (label, value, color) in enumerate(rows):
        y = margin_top + (index * row_height) + 8
        bar_y = y + 8
        bar_h = max(18.0, row_height * 0.55)
        bar_w = (max(0.0, value) / max_value) * plot_width if max_value > 0 else 0
        parts.append(f"<text x='{margin_left - 12}' y='{bar_y + bar_h * 0.75:.2f}' text-anchor='end' class='label'>{_esc(label)}</text>")
        parts.append(f"<rect x='{margin_left:.2f}' y='{bar_y:.2f}' width='{bar_w:.2f}' height='{bar_h:.2f}' rx='4' fill='{color}' />")
        parts.append(f"<text x='{margin_left + bar_w + 8:.2f}' y='{bar_y + bar_h * 0.75:.2f}' class='small'>{value:.2f}{_esc(unit)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _index_html(**kwargs: str | dict | float | None) -> str:
    bundle_summary = kwargs["bundle_summary"]
    overall = kwargs["overall"]
    graduation = kwargs["graduation"]
    gate_report = kwargs["gate_report"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Cluster Bundle Run Artifacts</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #111; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 20px 0; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 14px; background: #fafafa; }}
    .label {{ color: #555; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
    img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 10px; margin: 18px 0; }}
    ul {{ line-height: 1.6; }}
  </style>
</head>
<body>
  <h1>Cluster Bundle Run Artifacts</h1>
  <div class="grid">
    <div class="card"><div class="label">Retrieval Full</div><div class="value">{float(bundle_summary.get("retrieval_only_full_score") or overall.get("retrieval_only_score") or 0.0):.2f}</div></div>
    <div class="card"><div class="label">Bundle With Expert</div><div class="value">{float(bundle_summary.get("bundle_with_expert_score") or overall.get("adapter_score") or 0.0):.2f}</div></div>
    <div class="card"><div class="label">Token Savings</div><div class="value">{float(gate_report.get("token_savings_vs_retrieval_full") or 0.0):.2f}%</div></div>
    <div class="card"><div class="label">Quality Gain Vs Small</div><div class="value">{float(gate_report.get("quality_gain_vs_retrieval_small") or 0.0):.2f}</div></div>
  </div>
  <p>Retrieval small: <strong>{float(bundle_summary.get("retrieval_only_small_score") or 0.0):.2f}</strong><br/>Bundle without expert: <strong>{float(bundle_summary.get("bundle_without_expert_score") or 0.0):.2f}</strong></p>
  <p>Bundle gate: quality regression vs retrieval full <strong>{float(gate_report.get("quality_regression_vs_retrieval_full") or 0.0):.2f}</strong>, unsupported claim rate <strong>{float(gate_report.get("unsupported_claim_rate") or 0.0):.2f}</strong>, wrong citation rate <strong>{float(gate_report.get("wrong_citation_rate") or 0.0):.2f}</strong></p>
  <p>Legacy compatibility summary: graduation retrieval <strong>{float(graduation.get("retrieval_only_score") or 0.0):.2f}</strong>, graduation adapter <strong>{float(graduation.get("adapter_score") or 0.0):.2f}</strong></p>
  <p>Best eval loss: <strong>{float(kwargs["best_metric"] or 0.0):.4f}</strong><br/>Best checkpoint: <code>{_esc(str(kwargs["best_model_checkpoint"] or ""))}</code></p>
  <ul>
    <li><a href="{kwargs["summary_path"]}">Summary JSON</a></li>
    <li><a href="{kwargs["eval_csv_path"]}">Eval Curve CSV</a></li>
    <li><a href="{kwargs["category_csv_path"]}">Legacy Category Scores CSV</a></li>
    <li><a href="{kwargs["bundle_category_csv_path"]}">Bundle Category Scores CSV</a></li>
    <li><a href="{kwargs["case_csv_path"]}">Legacy Case Scores CSV</a></li>
    <li><a href="{kwargs["bundle_case_csv_path"]}">Bundle Case Outputs CSV</a></li>
    <li><a href="{kwargs["modes_csv_path"]}">Bundle Modes CSV</a></li>
  </ul>
  <img src="{kwargs["overall_svg_path"]}" alt="Overall scores" />
  <img src="{kwargs["category_svg_path"]}" alt="Legacy category deltas" />
  <img src="{kwargs["eval_svg_path"]}" alt="Eval loss curve" />
</body>
</html>"""


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    sys.exit(main())
