"""Формує окремий чесний звіт для п’яти engineering smoke запусків."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from runtime_contract import evaluate_ardupilot


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parents[1]
ISSUES = (
    "https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1",
    "https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/12",
    "https://github.com/Drone-Age/VINS-NEO/issues/28",
)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def reports_by_configuration(evidence_root):
    result = {}
    for path in evidence_root.glob("*/report/*.json"):
        try:
            report = load(path)
        except (OSError, ValueError):
            continue
        identifier = report.get("configuration_id")
        if not identifier:
            continue
        result.setdefault(identifier, []).append((path, report))
    for attempts in result.values():
        attempts.sort(key=lambda item: str(item[1].get("completed_at_utc", "")))
    return result


def evidence_reference(path, evidence_root):
    """Повертає переносне посилання всередині evidence root."""
    return path.resolve().relative_to(evidence_root.resolve()).as_posix()


def build(suite_path, evidence_root):
    suite = load(suite_path)
    items = suite.get("configurations", [])
    if len(items) != 5:
        raise ValueError("engineering smoke має містити рівно п’ять запусків")
    found = reports_by_configuration(evidence_root)
    ardupilot_requirement = suite["runtime_requirements"]["ardupilot"]
    results = []
    for order, item in enumerate(items, 1):
        attempts = found.get(item["configuration_id"], [])
        result = {
            "order": order,
            "configuration_id": item["configuration_id"],
            "status": "NOT_RUN",
            "verdict": "NOT_RUN",
            "metrics": None,
            "attempt_history": [],
            "runtime_contract": None,
        }
        if attempts:
            path, report = attempts[-1]
            result.update(
                {
                    "status": "RECORDED",
                    "verdict": report.get("verdict", "ABORT"),
                    "terminal_reason": report.get("terminal_reason"),
                    "run_id": report.get("run_id"),
                    "source_report": evidence_reference(path, evidence_root),
                    "validity": report.get("validity"),
                    "pose_graph": report.get("pose_graph"),
                    "metrics": report.get("metrics"),
                    "module_versions": report.get("module_versions"),
                    "runtime_contract": evaluate_ardupilot(
                        report, ardupilot_requirement
                    ),
                    "attempt_history": [
                        {
                            "run_id": attempt.get("run_id"),
                            "verdict": attempt.get("verdict", "ABORT"),
                            "terminal_reason": attempt.get("terminal_reason"),
                            "source_report": evidence_reference(
                                attempt_path, evidence_root
                            ),
                        }
                        for attempt_path, attempt in attempts
                    ],
                }
            )
            if not result["runtime_contract"]["passed"]:
                if result["verdict"] != "ABORT":
                    result["verdict"] = "FAIL"
                result["validity"] = {
                    "passed": False,
                    "failures": result["runtime_contract"]["failures"],
                }
        results.append(result)
    return {
        "schema": 1,
        "report_type": "vins-square-250-2k-pose-graph-engineering-smoke",
        "test_id": "VINS-POSE-GRAPH-SQUARE-250-2K-QUALIFICATION",
        "test_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "test_repository": "Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K",
        "issues": list(ISSUES),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_statistics": False,
        "runtime_requirements": suite["runtime_requirements"],
        "execution_backend": suite["execution_backend"],
        "reference": suite["reference"],
        "summary": {
            "recorded": sum(item["status"] == "RECORDED" for item in results),
            "not_run": sum(item["status"] == "NOT_RUN" for item in results),
            "passed": sum(item["verdict"] == "PASS" for item in results),
            "failed": sum(item["verdict"] == "FAIL" for item in results),
            "aborted": sum(item["verdict"] == "ABORT" for item in results),
        },
        "results": results,
    }


def create_pdf(report, output):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    story = [
        Paragraph("VINS Pose Graph: smoke квадрата 250 м / 2 км", styles["Title"]),
        Paragraph("Ці запуски не входять до офіційної статистики.", styles["BodyText"]),
        Paragraph("Issues: " + "; ".join(report["issues"]), styles["BodyText"]),
        Paragraph(
            "ArduPilot: очікується ArduCopter "
            f"{report['runtime_requirements']['ardupilot']['version']}; фактично: "
            + ", ".join(sorted({
                (item.get("runtime_contract") or {}).get("actual", {}).get("version")
                or "не зафіксовано"
                for item in report["results"] if item["status"] == "RECORDED"
            })) if report["summary"]["recorded"] else
            "ArduPilot: очікується ArduCopter "
            f"{report['runtime_requirements']['ardupilot']['version']}; фактично: немає записаних запусків.",
            styles["BodyText"],
        ),
        Spacer(1, 4 * mm),
    ]
    rows = [["№", "Конфігурація", "Стан", "Результат", "Run ID"]]
    for item in report["results"]:
        rows.append(
            [
                item["order"],
                item["configuration_id"],
                item["status"],
                item["verdict"],
                item.get("run_id", "-"),
            ]
        )
    table = Table(rows, colWidths=[12 * mm, 78 * mm, 30 * mm, 30 * mm, 42 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (-1, -1), "VinsReport"),
            ]
        )
    )
    details = []
    recorded = [item for item in report["results"] if item["status"] == "RECORDED"]
    if recorded:
        styles["Heading2"].fontName = "VinsReport-Bold"
        details.extend(
            [
                Spacer(1, 6 * mm),
                Paragraph("Зафіксовані причини", styles["Heading2"]),
            ]
        )
        for item in recorded:
            reason = item.get("terminal_reason") or "Причину не надано"
            details.append(
                Paragraph(
                    f"{item['configuration_id']}: {item['verdict']} - {reason}",
                    styles["BodyText"],
                )
            )
    SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=8 * mm, rightMargin=8 * mm
    ).build(story + [table] + details)


def main():
    parser = argparse.ArgumentParser(description="Формує окремий smoke-звіт")
    parser.add_argument(
        "--suite", type=Path,
        default=ROOT / "suites" / "vins-mono-square-250-2k-pose-graph-smoke.json",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=ROOT / "logs",
    )
    parser.add_argument(
        "--json", type=Path,
        default=PARENT / "output" / "json" / "vins-square-250-2k-pose-graph-smoke.json",
    )
    parser.add_argument(
        "--pdf", type=Path,
        default=PARENT / "output" / "pdf" / "vins-square-250-2k-pose-graph-smoke.pdf",
    )
    args = parser.parse_args()
    report = build(args.suite.resolve(), args.evidence_root.resolve())
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    create_pdf(report, args.pdf)


if __name__ == "__main__":
    main()
