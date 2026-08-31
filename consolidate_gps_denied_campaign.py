"""Формує окремі JSON/PDF для GPS-denied підкампанії без змішування з 42 польотами."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

from consolidate_pose_graph_campaign import arm_observed, report_groups
from runtime_contract import evaluate_ardupilot


ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parents[1]
ISSUES = (
    "https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/2",
    "https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/13",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def build(suite_path: Path, evidence_root: Path) -> dict:
    suite = load(suite_path)
    grouped = report_groups(evidence_root)
    results = []
    for run in suite["runs"]:
        profile_path = (suite_path.parent / run["profile"]).resolve()
        expected_hash = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        attempts = grouped.get(run["configuration_id"], [])
        history = []
        selected = None
        for report_path, report in attempts:
            exact = report.get("profile_sha256") == expected_hash
            armed = arm_observed(report_path)
            history.append({
                "run_id": report.get("run_id"),
                "verdict": report.get("verdict"),
                "armed_observed": armed,
                "exact_profile": exact,
                "report": report_path.relative_to(evidence_root).as_posix(),
            })
            if exact:
                selected = (report_path, report)
        item = {**run, "status": "NOT_RUN", "verdict": "NOT_RUN", "attempt_history": history}
        if selected is not None:
            report_path, report = selected
            runtime = evaluate_ardupilot(report, suite.get("runtime_requirements", {}).get("ardupilot", {
                "version": "4.7.0",
                "source_commit": "1511f27194f1dcc3728270883047bdf022b3fd53",
            }))
            metrics = report.get("metrics") or {}
            nav = metrics.get("navigation") or {}
            pose_graph_metrics = metrics.get("pose_graph") or {}
            pose_graph_profile = (report.get("pose_graph") or {}).get("profile") or {}
            false_match_threshold_m = float(
                pose_graph_profile.get("false_match_truth_distance_m", 20.0)
            )
            scenario_events_path = report_path.parent.parent / "raw" / "scenario-events.jsonl"
            audited_qualified_matches = 0
            audited_false_matches = 0
            maximum_truth_separation_m = None
            if scenario_events_path.is_file():
                for line in scenario_events_path.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        event.get("event") != "match_validated"
                        or event.get("qualified_for_route_metrics") is not True
                    ):
                        continue
                    separation = event.get("truth_match_separation_m")
                    if not finite(separation):
                        continue
                    separation = float(separation)
                    audited_qualified_matches += 1
                    maximum_truth_separation_m = (
                        separation
                        if maximum_truth_separation_m is None
                        else max(maximum_truth_separation_m, separation)
                    )
                    if separation > false_match_threshold_m:
                        audited_false_matches += 1
            false_match_audit = {
                "available": scenario_events_path.is_file(),
                "threshold_m": false_match_threshold_m,
                "qualified_match_count": audited_qualified_matches,
                "reported_false_match_count": pose_graph_metrics.get("false_match_count"),
                "audited_false_match_count": audited_false_matches,
                "maximum_truth_match_separation_m": maximum_truth_separation_m,
                "source": scenario_events_path.relative_to(evidence_root).as_posix()
                if scenario_events_path.is_file() else None,
            }
            selective_violation = any(entry["armed_observed"] for entry in history[:-1])
            valid = bool(
                report.get("verdict") == "PASS"
                and (report.get("validity") or {}).get("passed") is True
                and runtime.get("passed") is True
                and nav.get("route_source_set_2_fraction") == 1.0
                and nav.get("route_gnss_fusion_sample_count") == 0
                and nav.get("source_set_1_after_route_count") == 0
                and float(nav.get("route_external_nav_healthy_fraction", 0.0)) >= 0.999
                and false_match_audit["available"]
                and false_match_audit["audited_false_match_count"] == 0
                and not selective_violation
            )
            item.update({
                "status": "RECORDED",
                "verdict": report.get("verdict", "ABORT"),
                "terminal_reason": report.get("terminal_reason"),
                "run_id": report.get("run_id"),
                "armed_observed": arm_observed(report_path),
                "validity": report.get("validity") or {},
                "runtime_contract": runtime,
                "metrics": metrics,
                "navigation_evidence": nav,
                "pose_graph": report.get("pose_graph") or {},
                "false_match_audit": false_match_audit,
                "report": report_path.relative_to(evidence_root).as_posix(),
                "eligible_for_statistics": valid,
                "selective_post_arm_rerun_violation": selective_violation,
            })
        results.append(item)
    verdicts = []
    for mode in ("disabled", "loop", "map_build", "map_reuse_only", "loop_and_map_reuse"):
        flights = [item for item in results if item["mode"] == mode]
        eligible = [item for item in flights if item.get("eligible_for_statistics")]
        required = len(flights)
        corrected = [
            (((item.get("metrics") or {}).get("odometry") or {}).get("corrected") or {}).get("whole_route", {}).get("rmse_m")
            for item in eligible
        ]
        corrected = [float(value) for value in corrected if finite(value)]
        verdicts.append({
            "mode": mode,
            "passed": required > 0 and len(eligible) == required,
            "eligible_flights": len(eligible),
            "required_flights": required,
            "median_corrected_xy_rmse_m": statistics.median(corrected) if corrected else None,
        })
    return {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "suite_id": suite["suite_id"],
        "issues": list(ISSUES),
        "reference": {"source": "sim_truth", "used_as_vins_or_fcu_input": False},
        "navigation_contract": {
            "route_source_set": 2,
            "control_source": "VINS_ExternalNav",
            "gnss_fusion_allowed": False,
            "fallback_after_route_start_allowed": False,
        },
        "summary": {
            "planned": len(results),
            "recorded": sum(item["status"] == "RECORDED" for item in results),
            "valid": sum(bool(item.get("eligible_for_statistics")) for item in results),
            "failed_or_aborted": sum(item["status"] == "RECORDED" and not item.get("eligible_for_statistics") for item in results),
            "not_run": sum(item["status"] == "NOT_RUN" for item in results),
        },
        "verdicts": verdicts,
        "results": results,
    }


def create_pdf(report: dict, output: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    bold_candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    )
    font_path = next((path for path in font_candidates if path.is_file()), None)
    bold_path = next((path for path in bold_candidates if path.is_file()), None)
    if font_path is None or bold_path is None:
        raise RuntimeError("не знайдено шрифт із підтримкою української мови")
    pdfmetrics.registerFont(TTFont("VinsReport", str(font_path)))
    pdfmetrics.registerFont(TTFont("VinsReport-Bold", str(bold_path)))

    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "VinsReport-Bold"
    styles["BodyText"].fontName = "VinsReport"
    styles["Heading2"].fontName = "VinsReport-Bold"
    cell_style = styles["BodyText"].clone("GpsDeniedTableCell")
    cell_style.fontName = "VinsReport"
    cell_style.fontSize = 6.2
    cell_style.leading = 7.2
    header_style = cell_style.clone("GpsDeniedTableHeader")
    header_style.fontName = "VinsReport-Bold"
    header_style.textColor = colors.white
    header_style.alignment = 1

    def wrapped(value, header: bool = False):
        text = str(value if value is not None else "")
        text = text.replace("_", "_<wbr/>").replace("-", "-<wbr/>")
        return Paragraph(text, header_style if header else cell_style)

    def wrapped_rows(rows):
        return [
            [wrapped(value, row_index == 0) for value in row]
            for row_index, row in enumerate(rows)
        ]
    story = [
        Paragraph("GPS-denied кваліфікація VINS Pose Graph", styles["Title"]),
        Paragraph(
            f"Заплановано: {report['summary']['planned']}; записано: {report['summary']['recorded']}; "
            f"валідно: {report['summary']['valid']}; GNSS fusion на маршруті заборонено.",
            styles["BodyText"],
        ),
        Paragraph("Issues: " + "; ".join(report["issues"]), styles["BodyText"]),
        Spacer(1, 5 * mm),
    ]
    verdict_rows = [["Режим", "Валідні", "Потрібно", "Вердикт", "Медіана corrected RMSE, м"]]
    for item in report["verdicts"]:
        verdict_rows.append([
            item["mode"], item["eligible_flights"], item["required_flights"],
            "ПРОЙДЕНО" if item["passed"] else "НЕ ПРОЙДЕНО",
            "—" if item["median_corrected_xy_rmse_m"] is None else f"{item['median_corrected_xy_rmse_m']:.2f}",
        ])
    flights = [[
        "№", "Конфігурація", "Режим", "Стан", "Дистанція, м", "Source Set 2",
        "ExternalNav health", "Reset", "Regressive IMU", "False match",
    ]]
    for item in report["results"]:
        nav = item.get("navigation_evidence") or {}
        metrics = item.get("metrics") or {}
        false_audit = item.get("false_match_audit") or {}
        flights.append([
            item["run_number"], item["configuration_id"], item["mode"], item["verdict"],
            "—" if not finite(metrics.get("truth_distance_m")) else f"{float(metrics['truth_distance_m']):.1f}",
            nav.get("route_source_set_2_fraction", "—"),
            nav.get("route_external_nav_healthy_fraction", "—"),
            metrics.get("vins_reset_count", "—"),
            metrics.get("imu_regressive_timestamp_rejections", "—"),
            false_audit.get("audited_false_match_count", "—"),
        ])

    def add_table(rows, widths):
        table = Table(wrapped_rows(rows), colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
            ("FONTNAME", (0, 0), (-1, -1), "VinsReport"),
            ("FONTNAME", (0, 0), (-1, 0), "VinsReport-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([table, Spacer(1, 5 * mm)])

    add_table(verdict_rows, [52*mm, 28*mm, 28*mm, 40*mm, 48*mm])
    story.append(Paragraph("Результати всіх 15 запусків", styles["Heading2"]))
    add_table(
        flights,
        [8*mm, 63*mm, 31*mm, 19*mm, 22*mm, 18*mm, 24*mm, 14*mm, 18*mm, 18*mm],
    )

    story.extend([PageBreak(), Paragraph("Причини завершення", styles["Heading2"])])
    reasons = [["№", "Конфігурація", "Стан", "Після ARM", "Причина"]]
    for item in report["results"]:
        reasons.append([
            item["run_number"], item["configuration_id"], item["verdict"],
            "так" if item.get("armed_observed") else "ні",
            item.get("terminal_reason") or "завершено без terminal reason",
        ])
    add_table(reasons, [9*mm, 66*mm, 22*mm, 20*mm, 154*mm])

    story.extend([PageBreak(), Paragraph("Метрики Pose Graph та точності", styles["Heading2"])])
    pose_graph_rows = [[
        "№", "Режим", "Конфігурація", "loaded map", "current session",
        "Перший loaded, м", "Raw RMSE, м", "Corrected RMSE, м",
        "Correction jump, м", "False match",
    ]]
    for item in report["results"]:
        if item["mode"] == "disabled":
            continue
        metrics = item.get("metrics") or {}
        pose_graph = metrics.get("pose_graph") or {}
        odometry = metrics.get("odometry") or {}
        raw_rmse = ((odometry.get("raw") or {}).get("whole_route") or {}).get("rmse_m")
        corrected_rmse = ((odometry.get("corrected") or {}).get("whole_route") or {}).get("rmse_m")
        qualified = pose_graph.get("qualified_route_match_counts") or {}
        first_loaded = (pose_graph.get("first_qualified_match_route_distance_m") or {}).get("loaded_map")
        pose_graph_rows.append([
            item["run_number"], item["mode"], item["configuration_id"],
            qualified.get("loaded_map", 0), qualified.get("current_session", 0),
            "—" if not finite(first_loaded) else f"{float(first_loaded):.2f}",
            "—" if not finite(raw_rmse) else f"{float(raw_rmse):.2f}",
            "—" if not finite(corrected_rmse) else f"{float(corrected_rmse):.2f}",
            "—" if not finite(pose_graph.get("correction_jump_max_m"))
            else f"{float(pose_graph['correction_jump_max_m']):.2f}",
            (item.get("false_match_audit") or {}).get("audited_false_match_count", "—"),
        ])
    add_table(
        pose_graph_rows,
        [8*mm, 31*mm, 52*mm, 20*mm, 22*mm, 24*mm, 22*mm, 27*mm, 27*mm, 20*mm],
    )
    SimpleDocTemplate(
        str(output), pagesize=landscape(A4), leftMargin=8*mm, rightMargin=8*mm,
        topMargin=8*mm, bottomMargin=8*mm,
    ).build(story)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "logs")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    stem = args.suite.stem
    json_path = args.json or PARENT / "output" / "json" / f"{stem}.json"
    pdf_path = args.pdf or PARENT / "output" / "pdf" / f"{stem}.pdf"
    report = build(args.suite.resolve(), args.evidence_root.resolve())
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    create_pdf(report, pdf_path)


if __name__ == "__main__":
    main()
