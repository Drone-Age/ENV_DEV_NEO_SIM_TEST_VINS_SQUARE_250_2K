"""Формує незмінний звіт кампанії Pose Graph із 42 польотів і семи висновків."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
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


def rmse(values):
    values = [float(value) for value in values if math.isfinite(float(value))]
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else math.inf


def report_groups(evidence_root):
    reports = {}
    for path in evidence_root.glob("*/report/*.json"):
        try:
            report = load(path)
        except (OSError, ValueError):
            continue
        config = report.get("configuration_id")
        if not config or "metrics" not in report:
            continue
        reports.setdefault(config, []).append((path, report))
    for attempts in reports.values():
        attempts.sort(key=lambda item: str(item[1].get("completed_at_utc", "")))
    return reports


def profile_sha256(suite_path, run):
    profile_path = (Path(suite_path).parent / run["profile"]).resolve()
    return hashlib.sha256(profile_path.read_bytes()).hexdigest()


def evidence_reference(path, evidence_root):
    """Повертає переносне посилання всередині кореня evidence."""
    return path.resolve().relative_to(evidence_root.resolve()).as_posix()


def match_timeline(report_path):
    """Завантажує повний аудит підтверджених збігів без SIM truth як входу VINS."""
    events_path = report_path.parents[1] / "raw" / "pose-graph-events.json"
    if not events_path.is_file():
        return []
    try:
        events = load(events_path)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(events, list):
        return []
    return [event for event in events if event.get("event") == "match_validated"]


def first_timeline_events_by_source(item):
    """Стислий PDF timeline; повний список подій залишається у JSON."""
    selected = []
    seen_sources = set()
    for event in item.get("match_timeline", []):
        source = event.get("match_source")
        if not source or source in seen_sources or event.get("false_match") is True:
            continue
        seen_sources.add(source)
        selected.append(event)
    return selected


def flight_eligible(item):
    """Дозволяє статистику лише для повністю валідного зафіксованого польоту."""
    metrics = item.get("metrics") or {}
    pose_graph = metrics.get("pose_graph") or {}
    return (
        item.get("status") == "RECORDED"
        and item.get("verdict") == "PASS"
        and (item.get("validity") or {}).get("passed") is True
        and (item.get("runtime_contract") or {}).get("passed") is True
        and int(pose_graph.get("false_match_count", -1)) == 0
        and item.get("selective_post_arm_rerun_violation") is not True
    )


def first_match_event(item, source, *, loop=False):
    return next(
        (
            event for event in item.get("match_timeline", [])
            if event.get("match_source") == source
            and event.get("false_match") is not True
            and event.get("qualified_for_route_metrics") is not False
            and (
                not loop
                or (
                    event.get("current_route_leg") == "return"
                    and event.get("matched_route_leg") == "outbound"
                )
            )
        ),
        None,
    )


def correct_match(item, source, maximum_progress_m, *, loop=False):
    if not flight_eligible(item):
        return False
    event = first_match_event(item, source, loop=loop)
    if event is None:
        return False
    try:
        current_distance = float(event["current_route_distance_m"])
    except (KeyError, TypeError, ValueError):
        return False
    if loop:
        try:
            return_progress = float(event.get("return_progress_m"))
        except (TypeError, ValueError):
            # Runtime називає другу половину маршруту return; тут це другий круг.
            return_progress = current_distance - 1000.0
        return 0.0 <= return_progress <= maximum_progress_m
    return current_distance <= maximum_progress_m


def map_artifact_ready(item, altitude_m):
    manifest = ((item.get("pose_graph") or {}).get("map_manifest") or {})
    metadata = manifest.get("metadata") or {}
    try:
        source_altitude_m = float(metadata["altitude_m"])
        keyframe_count = int(manifest["keyframe_count"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        flight_eligible(item)
        and manifest.get("artifact_type") == "vins_mono_pose_graph"
        and manifest.get("immutable") is True
        and keyframe_count > 0
        and bool(manifest.get("files"))
        and source_altitude_m == float(altitude_m)
    )


def arm_observed(report_path):
    events = report_path.parents[1] / "raw" / "scenario-events.jsonl"
    if not events.is_file():
        return False
    text = events.read_text(encoding="utf-8", errors="replace")
    return (
        '"event": "GATEWAY_LOITER_BOOTSTRAP_STARTED"' in text
        or '"armed": true' in text
        or "mission_stage=ARMED" in text
    )


def interval_metric(report_path, field, start_distance=0.0, leg=None):
    telemetry = report_path.parents[1] / "raw" / "telemetry.csv"
    if not telemetry.is_file():
        return math.inf
    route_sequence_bounds = None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        route_start_sequence = int(report["route_start_sequence"])
        route_final_sequence = int(report["route_final_sequence"])
        if route_final_sequence >= route_start_sequence:
            route_sequence_bounds = (route_start_sequence, route_final_sequence)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        # Старі evidence можуть не містити меж sequence. Для них зберігаємо
        # попередню поведінку, але нові офіційні запуски завжди фільтруємо.
        pass
    with telemetry.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    values = []
    for row in rows:
        try:
            route_distance = float(row["route_distance_m"])
            value = float(row[field])
            if route_sequence_bounds is not None:
                current_sequence = int(row["current_sequence"])
        except (KeyError, TypeError, ValueError):
            continue
        if route_distance < start_distance:
            continue
        if leg is not None and row.get("leg") != leg:
            continue
        if route_sequence_bounds is not None and not (
            route_sequence_bounds[0] <= current_sequence <= route_sequence_bounds[1]
        ):
            continue
        if math.isfinite(value):
            values.append(value)
    return rmse(values)


def improvement(baseline, enabled):
    if not math.isfinite(baseline) or baseline <= 0 or not math.isfinite(enabled):
        return -math.inf
    return (baseline - enabled) / baseline


def median(values):
    finite = [value for value in values if math.isfinite(value)]
    return statistics.median(finite) if finite else -math.inf


def gain_distribution(values):
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return {"count": 0, "median": -math.inf, "minimum": -math.inf, "maximum": -math.inf, "p25": -math.inf, "p75": -math.inf}
    def quantile(fraction):
        position = (len(finite) - 1) * fraction
        lower = int(math.floor(position)); upper = int(math.ceil(position))
        if lower == upper:
            return finite[lower]
        return finite[lower] + (finite[upper] - finite[lower]) * (position - lower)
    return {
        "count": len(finite), "median": statistics.median(finite),
        "minimum": finite[0], "maximum": finite[-1],
        "p25": quantile(0.25), "p75": quantile(0.75),
    }


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def nested_number(item, *keys, default=math.inf):
    value = item.get("metrics") or {}
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def build(suite_path, evidence_root):
    suite = load(suite_path)
    if suite.get("official_flight_count") != 42 or len(suite.get("runs", [])) != 42:
        raise ValueError("офіційна кампанія має містити рівно 42 польоти")
    found = report_groups(evidence_root)
    ardupilot_requirement = suite["runtime_requirements"]["ardupilot"]
    results = []
    by_id = {}
    for run in suite["runs"]:
        expected_profile_sha256 = profile_sha256(suite_path, run)
        attempts = [
            attempt
            for attempt in found.get(run["configuration_id"], [])
            if attempt[1].get("profile_sha256") == expected_profile_sha256
        ]
        selected = attempts[-1] if attempts else None
        selective_rerun = len(attempts) > 1 and any(
            arm_observed(path) for path, _report in attempts[:-1]
        )
        result = {
            **run,
            "status": "NOT_RUN",
            "verdict": "NOT_RUN",
            "metrics": None,
            "runtime_contract": None,
        }
        if selected:
            path, report = selected
            result.update({
                "status": "RECORDED",
                "verdict": report.get("verdict", "ABORT"),
                "run_id": report.get("run_id"),
                "source_report": evidence_reference(path, evidence_root),
                "validity": report.get("validity"),
                "pose_graph": report.get("pose_graph"),
                "metrics": report.get("metrics"),
                "module_versions": report.get("module_versions"),
                "runtime_contract": evaluate_ardupilot(
                    report, ardupilot_requirement
                ),
                "match_timeline": match_timeline(path),
                "attempt_history": [
                    {
                        "run_id": attempt.get("run_id"),
                        "verdict": attempt.get("verdict"),
                        "terminal_reason": attempt.get("terminal_reason"),
                        "arm_observed": arm_observed(attempt_path),
                        "source_report": evidence_reference(
                            attempt_path, evidence_root
                        ),
                    }
                    for attempt_path, attempt in attempts
                ],
                "selective_post_arm_rerun_violation": selective_rerun,
            })
            if selective_rerun:
                result["verdict"] = "FAIL"
                result["validity"] = {
                    "passed": False,
                    "failures": ["SELECTIVE_POST_ARM_RERUN_OBSERVED"],
                }
            if not result["runtime_contract"]["passed"]:
                result["verdict"] = "FAIL"
                validity = result.get("validity") or {"passed": False, "failures": []}
                result["validity"] = {
                    "passed": False,
                    "failures": [
                        *validity.get("failures", []),
                        *result["runtime_contract"]["failures"],
                    ],
                }
            result["_report_path"] = path
        results.append(result)
        by_id[result["configuration_id"]] = result

    comparisons = []
    groups = {}
    for result in results:
        if result.get("pair_id"):
            groups.setdefault(result["pair_id"], []).append(result)
    for pair_id, items in groups.items():
        off = next((item for item in items if item["mode"] == "disabled"), None)
        for enabled in (item for item in items if item["mode"] != "disabled"):
            metrics = enabled.get("metrics") or {}
            source = "current_session" if enabled["mode"] == "loop" else "loaded_map"
            event = first_match_event(enabled, source, loop=enabled["mode"] == "loop")
            first = event.get("current_route_distance_m") if event else None
            return_progress = event.get("return_progress_m") if event else None
            segment = "return" if enabled["mode"] == "loop" else None
            start = float(first) if first is not None else math.inf
            eligible = bool(off) and flight_eligible(off) and flight_eligible(enabled)
            enabled_rmse = interval_metric(enabled.get("_report_path", Path(".")), "corrected_xy_error_m", start, segment) if eligible else math.inf
            baseline_rmse = interval_metric(off.get("_report_path", Path(".")), "corrected_xy_error_m", start, segment) if eligible else math.inf
            comparisons.append({
                "pair_id": pair_id,
                "off_configuration_id": off["configuration_id"] if off else None,
                "on_configuration_id": enabled["configuration_id"],
                "mode": enabled["mode"],
                "source_altitude_m": enabled.get("source_altitude_m"),
                "target_altitude_m": enabled["target_altitude_m"],
                "match_source": source,
                "eligible": eligible,
                "first_match_route_distance_m": first,
                "first_match_lap2_progress_m": return_progress,
                "off_rmse_m": baseline_rmse,
                "on_rmse_m": enabled_rmse,
                "improvement_fraction": improvement(baseline_rmse, enabled_rmse),
            })

    def relevant(mode, source=None, target=None):
        return [item for item in comparisons if item["mode"] == mode
                and (source is None or item["source_altitude_m"] == source)
                and (target is None or item["target_altitude_m"] == target)]

    loop = relevant("loop")
    loop_matches = [
        item for item in loop
        if correct_match(
            by_id[item["on_configuration_id"]],
            "current_session",
            100.0,
            loop=True,
        )
    ]
    loop_gains = [item["improvement_fraction"] for item in loop]
    loop_endpoint_ok = all(
        nested_number(by_id[item["on_configuration_id"]], "odometry", "corrected", "whole_route", "endpoint_m")
        <= nested_number(by_id[item["off_configuration_id"]], "odometry", "corrected", "whole_route", "endpoint_m", default=-math.inf)
        for item in loop
    ) if len(loop) == 5 else False
    loop_p95_ok = all(
        nested_number(by_id[item["on_configuration_id"]], "odometry", "corrected", "return", "p95_m")
        <= nested_number(by_id[item["off_configuration_id"]], "odometry", "corrected", "return", "p95_m", default=-math.inf)
        for item in loop
    ) if len(loop) == 5 else False
    verdicts = {
        "loop_closure": {
            "passed": len(loop_matches) == 5 and median(loop_gains) >= 0.5
            and sum(value > 0 for value in loop_gains) >= 4 and loop_endpoint_ok and loop_p95_ok,
            "correct_matches": len(loop_matches), "required_matches": 5,
            "median_improvement_fraction": median(loop_gains),
            "improved_pairs": sum(value > 0 for value in loop_gains),
            "p95_not_worse": loop_p95_ok, "endpoint_not_worse": loop_endpoint_ok,
            "improvement_distribution": gain_distribution(loop_gains),
        }
    }
    map_builds = {
        altitude: next(
            (
                item for item in results
                if item["mode"] == "map_build"
                and item["target_altitude_m"] == altitude
            ),
            {},
        )
        for altitude in (150, 40)
    }
    map_quality = {
        altitude: map_artifact_ready(item, altitude)
        for altitude, item in map_builds.items()
    }
    for altitude in (150, 40):
        items = relevant("map_reuse_only", altitude, altitude)
        gains = [item["improvement_fraction"] for item in items]
        correct = sum(
            correct_match(
                by_id[item["on_configuration_id"]], "loaded_map", 100.0
            )
            and item["eligible"]
            for item in items
        )
        verdicts[f"same_altitude_map_reuse_{altitude}m"] = {
            "passed": map_quality[altitude] and len(items) == 3 and correct == 3 and median(gains) >= 0.5 and sum(value > 0 for value in gains) >= 2,
            "map_quality_gate": map_quality[altitude],
            "correct_matches": correct, "required_matches": 3,
            "median_improvement_fraction": median(gains),
            "improved_pairs": sum(value > 0 for value in gains),
            "improvement_distribution": gain_distribution(gains),
        }
    for source, target in ((150, 40), (40, 150)):
        items = relevant("map_reuse_only", source, target)
        gains = [item["improvement_fraction"] for item in items]
        correct = sum(
            correct_match(
                by_id[item["on_configuration_id"]], "loaded_map", 150.0
            )
            and item["eligible"]
            for item in items
        )
        viable = map_quality[source] and len(items) == 3 and correct == 3
        verdicts[f"cross_altitude_{source}to{target}"] = {
            "passed": viable,
            "relocalization_viable": viable,
            "map_quality_gate": map_quality[source],
            "accuracy_benefit_confirmed": viable and median(gains) >= 0.5,
            "correct_matches": correct, "required_matches": 3,
            "median_improvement_fraction": median(gains),
            "improvement_distribution": gain_distribution(gains),
        }

    loop_isolated_reference_rmse = median([
        nested_number(item, "odometry", "corrected", "whole_route", "rmse_m")
        for item in results if item["mode"] == "loop" and flight_eligible(item)
    ])
    combined_rows = []
    for run in (item for item in results if item["mode"] == "loop_and_map_reuse"):
        metrics = run.get("metrics") or {}
        first = metrics.get("pose_graph", {}).get("first_match_route_distance_m", {}).get("loaded_map")
        baseline_id = run_id_for(results, "map_reuse_only", "disabled", run["target_altitude_m"], run["seed"])
        isolated_id = run_id_for(results, "map_reuse_only", "map_reuse_only", run["target_altitude_m"], run["seed"], run["source_altitude_m"])
        baseline = by_id.get(baseline_id)
        isolated = by_id.get(isolated_id)
        eligible = bool(baseline and isolated) and all(
            flight_eligible(item) for item in (run, baseline, isolated)
        )
        start = float(first) if first is not None else math.inf
        on_rmse = interval_metric(run.get("_report_path", Path(".")), "corrected_xy_error_m", start) if eligible else math.inf
        off_rmse = interval_metric(baseline.get("_report_path", Path(".")), "corrected_xy_error_m", start) if eligible else math.inf
        isolated_rmse = interval_metric(isolated.get("_report_path", Path(".")), "corrected_xy_error_m", start) if eligible else math.inf
        best_isolated_rmse = min(isolated_rmse, loop_isolated_reference_rmse)
        combined_rows.append({
            "configuration_id": run["configuration_id"], "source_altitude_m": run["source_altitude_m"],
            "target_altitude_m": run["target_altitude_m"], "first_loaded_map_match_m": first,
            "eligible": eligible,
            "correct_loaded_map_match_on_lap1": correct_match(run, "loaded_map", 100.0),
            "correct_current_session_match_on_lap2": correct_match(
                run, "current_session", 100.0, loop=True
            ),
            "improvement_fraction": improvement(off_rmse, on_rmse),
            "isolated_map_rmse_m": isolated_rmse,
            "isolated_loop_reference_rmse_m": loop_isolated_reference_rmse,
            "best_isolated_rmse_m": best_isolated_rmse,
            "combined_rmse_m": on_rmse,
            "not_worse_than_isolated_by_5pct": math.isfinite(best_isolated_rmse) and on_rmse <= 1.05 * best_isolated_rmse,
            "match_counts": metrics.get("pose_graph", {}).get("match_counts", {}),
        })
    for label, selector in (
        ("combined_same_altitude", lambda row: row["source_altitude_m"] == row["target_altitude_m"]),
        ("combined_cross_altitude", lambda row: row["source_altitude_m"] != row["target_altitude_m"]),
    ):
        items = [row for row in combined_rows if selector(row)]
        gains = [row["improvement_fraction"] for row in items]
        verdicts[label] = {
            "passed": len(items) == 6
            and all(map_quality[row["source_altitude_m"]] for row in items)
            and all(
                row["eligible"]
                and row["correct_loaded_map_match_on_lap1"]
                and row["correct_current_session_match_on_lap2"]
                for row in items
            )
            and median(gains) >= 0.5
            and all(row["not_worse_than_isolated_by_5pct"] for row in items),
            "loaded_map_on_lap1": sum(row["correct_loaded_map_match_on_lap1"] for row in items),
            "current_session_on_lap2": sum(row["correct_current_session_match_on_lap2"] for row in items),
            "required": 6, "median_improvement_fraction": median(gains),
            "map_quality_gates": {
                str(altitude): map_quality[altitude]
                for altitude in sorted({row["source_altitude_m"] for row in items})
            },
            "all_within_isolated_5pct": all(row["not_worse_than_isolated_by_5pct"] for row in items),
            "source_contributions": [row["match_counts"] for row in items],
            "improvement_distribution": gain_distribution(gains),
        }

    public_results = [{key: value for key, value in item.items() if not key.startswith("_")} for item in results]
    return {
        "schema": 2,
        "report_type": "vins-mono-square-250-2k-pose-graph-qualification",
        "test_id": "VINS-POSE-GRAPH-SQUARE-250-2K-QUALIFICATION",
        "test_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "test_repository": "Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K",
        "issues": list(ISSUES),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "suite_id": suite["suite_id"],
        "execution_backend": suite["execution_backend"],
        "reference": suite["reference"],
        "route_contract": suite["route_contract"],
        "runtime_requirements": suite["runtime_requirements"],
        "official_flight_count": 42,
        "summary": {
            "recorded": sum(item["status"] == "RECORDED" for item in results),
            "not_run": sum(item["status"] == "NOT_RUN" for item in results),
            "valid": sum(item.get("validity", {}).get("passed") is True for item in results),
            "failed_or_aborted": sum(item["verdict"] in {"FAIL", "ABORT"} for item in results),
            "selective_post_arm_rerun_violations": sum(
                item.get("selective_post_arm_rerun_violation") is True for item in results
            ),
            "eligible_for_statistics": sum(flight_eligible(item) for item in results),
            "map_quality_gates": {
                str(altitude): passed
                for altitude, passed in map_quality.items()
            },
        },
        "verdicts": verdicts,
        "paired_comparisons": comparisons,
        "combined_comparisons": combined_rows,
        "results": public_results,
    }


def run_id_for(results, stage, mode, target, seed, source=None):
    for item in results:
        if item["stage"] == stage and item["mode"] == mode and item["target_altitude_m"] == target and item["seed"] == seed and (source is None or item.get("source_altitude_m") == source):
            return item["configuration_id"]
    return None


def create_pdf(report, output):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    for style_name in ("Title", "BodyText", "Heading2"):
        styles[style_name].fontName = "VinsReport-Bold" if style_name != "BodyText" else "VinsReport"
    cell_style = styles["BodyText"].clone("TableCell")
    cell_style.fontName = "VinsReport"
    cell_style.fontSize = 5.8
    cell_style.leading = 6.8

    def wrapped(value):
        text = str(value if value is not None else "")
        return Paragraph(text.replace("_", "_<wbr/>").replace("-", "-<wbr/>"), cell_style)

    def verdict_evidence(verdict):
        parts = []
        if "correct_matches" in verdict:
            parts.append(f"правильні збіги: {verdict['correct_matches']}/{verdict.get('required_matches', '?')}")
        if "improved_pairs" in verdict:
            parts.append(f"покращені пари: {verdict['improved_pairs']}")
        if "loaded_map_on_lap1" in verdict:
            parts.append(f"loaded map на крузі 1: {verdict['loaded_map_on_lap1']}/{verdict.get('required', '?')}")
            parts.append(f"current session на крузі 2: {verdict['current_session_on_lap2']}/{verdict.get('required', '?')}")
        if "accuracy_benefit_confirmed" in verdict:
            parts.append("користь для точності: " + ("так" if verdict["accuracy_benefit_confirmed"] else "ні"))
        return "; ".join(parts) or "немає записаних польотів"
    expected_ardupilot = report["runtime_requirements"]["ardupilot"]
    actual_ardupilot = sorted({
        (item.get("runtime_contract") or {}).get("actual", {}).get("version") or "не зафіксовано"
        for item in report["results"] if item["status"] == "RECORDED"
    })
    story = [Paragraph("VINS Pose Graph: кваліфікація Loop Closure і Map Reuse", styles["Title"]),
             Paragraph(
                 f"Офіційна кампанія: 42 польоти. Версія тесту: {report['test_version']}. "
                 f"Сформовано: {report['generated_at_utc']}", styles["BodyText"]), Spacer(1, 4*mm)]
    story.extend([
        Paragraph(
            "Issues: " + "; ".join(report["issues"]),
            styles["BodyText"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            f"ArduPilot: очікується ArduCopter {expected_ardupilot['version']} "
            f"({expected_ardupilot['source_commit']}); фактично: "
            f"{', '.join(actual_ardupilot) if actual_ardupilot else 'немає записаних польотів'}.",
            styles["BodyText"],
        ),
        Spacer(1, 3 * mm),
    ])
    verdict_rows = [["Висновок", "Результат", "Медіанне покращення", "Підтвердження"]]
    for name, verdict in report["verdicts"].items():
        gain = verdict.get("median_improvement_fraction", -math.inf)
        result_text = "ПРОЙДЕНО" if verdict["passed"] else (
            "НЕМАЄ ДАНИХ" if report["summary"]["recorded"] == 0 else "НЕ ПРОЙДЕНО"
        )
        verdict_rows.append([name, result_text,
                             f"{100*gain:.1f}%" if math.isfinite(gain) else "-",
                             verdict_evidence(verdict)])
    table = Table(verdict_rows, colWidths=[52*mm, 34*mm, 37*mm, 139*mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .3, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("FONTSIZE", (0,0), (-1,-1), 7), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    class CampaignChart(Flowable):
        def __init__(self, title, series):
            super().__init__(); self.width = 260*mm; self.height = 48*mm
            self.title, self.series = title, series
        def draw(self):
            canvas = self.canv; left, bottom = 14*mm, 8*mm
            right, top = self.width-5*mm, self.height-8*mm
            values = [value for _name, points, _colour in self.series for _x, value in points if math.isfinite(value)]
            canvas.setFont("VinsReport-Bold", 8); canvas.drawString(left, self.height-5*mm, self.title)
            if not values:
                canvas.setFont("VinsReport", 7); canvas.drawString(left, bottom+8*mm, "Немає записаних даних польотів"); return
            y_min, y_max = 0.0, max(values)
            if y_max <= 0: y_max = 1.0
            canvas.setStrokeColor(colors.grey); canvas.line(left,bottom,right,bottom); canvas.line(left,bottom,left,top)
            for name, points, colour in self.series:
                canvas.setStrokeColor(colors.HexColor(colour)); canvas.setLineWidth(.8)
                drawn = [(left+(x-1)/41*(right-left), bottom+value/y_max*(top-bottom)) for x,value in points if math.isfinite(value)]
                for first, second in zip(drawn, drawn[1:]): canvas.line(first[0],first[1],second[0],second[1])
                canvas.setFillColor(colors.HexColor(colour)); canvas.setFont("VinsReport", 6.5); canvas.drawString(right-38*mm, top-(self.series.index((name,points,colour))*4+3)*mm, name)
            canvas.setFillColor(colors.black); canvas.setFont("VinsReport", 6)
            canvas.drawString(left,bottom-3*mm,"політ 1"); canvas.drawRightString(right,bottom-3*mm,"політ 42")
    raw_points = [(item["run_number"], nested_number(item, "odometry", "raw", "whole_route", "rmse_m")) for item in report["results"]]
    corrected_points = [(item["run_number"], nested_number(item, "odometry", "corrected", "whole_route", "rmse_m")) for item in report["results"]]
    match_points = []
    for item in report["results"]:
        distances = ((item.get("metrics") or {}).get("pose_graph", {}).get("first_match_route_distance_m", {}) or {}).values()
        finite = [float(value) for value in distances if value is not None and math.isfinite(float(value))]
        match_points.append((item["run_number"], min(finite) if finite else math.inf))
    story += [table, Spacer(1, 4*mm),
              CampaignChart("Сира та скоригована XY RMSE за польотами", [("сира", raw_points, "#2563EB"), ("скоригована", corrected_points, "#16A34A")]),
              CampaignChart("Відстань маршруту до першого підтвердженого збігу", [("перший збіг", match_points, "#7C3AED")]),
              Spacer(1, 5*mm)]
    map_rows = [["Висота", "Run ID", "Keyframes", "Loops", "Файлів", "Immutable", "Quality gate"]]
    for altitude in (150, 40):
        build_run = next(
            (
                item for item in report["results"]
                if item["mode"] == "map_build"
                and item["target_altitude_m"] == altitude
            ),
            {},
        )
        manifest = ((build_run.get("pose_graph") or {}).get("map_manifest") or {})
        metadata = manifest.get("metadata") or {}
        map_rows.append([
            altitude,
            build_run.get("run_id", "-"),
            manifest.get("keyframe_count", "-"),
            metadata.get("loop_count", "-"),
            len(manifest.get("files", [])),
            "так" if manifest.get("immutable") is True else "ні",
            "PASS" if report["summary"]["map_quality_gates"].get(str(altitude)) else "FAIL",
        ])
    maps = Table(map_rows, colWidths=[24*mm, 58*mm, 28*mm, 24*mm, 24*mm, 28*mm, 30*mm], repeatRows=1)
    maps.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 6.5), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))

    timeline_rows = [["Політ", "Джерело", "Current KF", "Matched KF", "Поточна відстань/leg", "Зіставлена відстань/leg", "DBoW", "RANSAC/PnP", "Epoch"]]
    for item in report["results"]:
        for event in first_timeline_events_by_source(item):
            timeline_rows.append([
                item["run_number"],
                event.get("match_source", "-"),
                event.get("current_keyframe", "-"),
                event.get("matched_keyframe", "-"),
                f"{event.get('current_route_distance_m', '-')} / {event.get('current_route_leg', '-')}",
                f"{event.get('matched_route_distance_m', '-')} / {event.get('matched_route_leg', '-')}",
                event.get("dbow_score", "-"),
                f"{event.get('ransac_inliers', '-')} / {event.get('pnp_inliers', '-')}",
                event.get("correction_epoch", "-"),
            ])
    if len(timeline_rows) == 1:
        timeline_rows.append(["-", "Немає записаних збігів", "-", "-", "-", "-", "-", "-", "-"])
    timeline = Table(timeline_rows, colWidths=[14*mm, 31*mm, 21*mm, 23*mm, 46*mm, 46*mm, 20*mm, 28*mm, 16*mm], repeatRows=1)
    timeline.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 5.8), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    story += [Paragraph("Походження та quality gate карт", styles["Heading2"]), maps,
              Spacer(1, 5*mm), Paragraph("Timeline перших підтверджених збігів кожного джерела", styles["Heading2"]), timeline,
              Spacer(1, 5*mm)]
    pair_rows = [["Пара", "Режим / карта", "Збіг, м", "OFF RMSE", "ON RMSE", "Покращення"]]
    for item in report["paired_comparisons"]:
        pair_rows.append([
            item["pair_id"],
            f"{item['mode']} {item.get('source_altitude_m')}→{item['target_altitude_m']}",
            item.get("first_match_route_distance_m"),
            f"{item['off_rmse_m']:.2f}" if math.isfinite(item["off_rmse_m"]) else "немає",
            f"{item['on_rmse_m']:.2f}" if math.isfinite(item["on_rmse_m"]) else "немає",
            f"{100*item['improvement_fraction']:.1f}%" if math.isfinite(item["improvement_fraction"]) else "немає",
        ])
    pairs = Table(pair_rows, colWidths=[40*mm, 70*mm, 28*mm, 30*mm, 30*mm, 28*mm], repeatRows=1)
    pairs.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 6.5), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    combined_rows = [["Конфігурація", "Карта", "Ціль", "Збіг із картою", "Покращення", "Не гірше за ізольований +5%"]]
    for item in report["combined_comparisons"]:
        combined_rows.append([
            item["configuration_id"], item["source_altitude_m"], item["target_altitude_m"],
            item.get("first_loaded_map_match_m"),
            f"{100*item['improvement_fraction']:.1f}%" if math.isfinite(item["improvement_fraction"]) else "немає",
            "так" if item["not_worse_than_isolated_by_5pct"] else "ні",
        ])
    combined_rows = [combined_rows[0]] + [
        [wrapped(row[0]), *row[1:]] for row in combined_rows[1:]
    ]
    combined = Table(combined_rows, colWidths=[112*mm, 20*mm, 20*mm, 32*mm, 27*mm, 55*mm], repeatRows=1)
    combined.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 6.5), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    story += [Paragraph("Парні порівняння OFF/ON", styles["Heading2"]), pairs,
              Spacer(1, 5*mm), Paragraph("Порівняння комбінованого режиму", styles["Heading2"]), combined,
              Spacer(1, 5*mm), Paragraph("Raw/corrected точність за сегментами", styles["Heading2"])]
    accuracy_rows = [["№", "Raw весь", "Raw круг 1", "Raw круг 2", "Raw endpoint", "Corrected весь", "Corrected круг 1", "Corrected круг 2", "Post-match", "Alt P95", "Yaw P95"]]
    def number_text(value):
        return f"{value:.2f}" if math.isfinite(value) else "-"
    def metric_text(item, stream, segment, field="rmse_m"):
        return number_text(nested_number(item, "odometry", stream, segment, field))
    for item in report["results"]:
        accuracy_rows.append([
            item["run_number"],
            metric_text(item, "raw", "whole_route"),
            metric_text(item, "raw", "outbound"),
            metric_text(item, "raw", "return"),
            metric_text(item, "raw", "whole_route", "endpoint_m"),
            metric_text(item, "corrected", "whole_route"),
            metric_text(item, "corrected", "outbound"),
            metric_text(item, "corrected", "return"),
            metric_text(item, "corrected", "post_match"),
            number_text(nested_number(item, "odometry", "corrected", "altitude", "whole_route", "p95_m")),
            number_text(nested_number(item, "odometry", "corrected", "yaw", "whole_route", "p95_m")),
        ])
    accuracy = Table(accuracy_rows, colWidths=[10*mm, 23*mm, 24*mm, 22*mm, 24*mm, 29*mm, 31*mm, 28*mm, 25*mm, 21*mm, 21*mm], repeatRows=1)
    accuracy.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 5.8), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    spatial_rows = [["№", "Сторона 1", "Сторона 2", "Сторона 3", "Сторона 4", "Кут 0", "Кут 1", "Кут 2", "Кут 3"]]
    for item in report["results"]:
        spatial_rows.append([
            item["run_number"],
            *[
                number_text(nested_number(item, "odometry", "corrected", "sides", str(index), "rmse_m"))
                for index in range(1, 5)
            ],
            *[
                number_text(nested_number(item, "odometry", "corrected", "corners", str(index), "rmse_m"))
                for index in range(4)
            ],
        ])
    spatial = Table(spatial_rows, colWidths=[12*mm] + [32*mm]*8, repeatRows=1)
    spatial.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 6.2), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    story += [
        accuracy,
        Spacer(1, 5*mm),
        Paragraph("Corrected XY RMSE за сторонами та кутами", styles["Heading2"]),
        spatial,
        Spacer(1, 5*mm),
        Paragraph("Усі 42 заплановані польоти", styles["Heading2"]),
    ]
    rows = [["№", "Конфігурація", "Етап", "Режим", "Карта", "Ціль", "Seed", "Стан"]]
    for item in report["results"]:
        rows.append([item["run_number"], wrapped(item["configuration_id"]), item["stage"], item["mode"], item.get("source_altitude_m"), item["target_altitude_m"], item["seed"], item["verdict"]])
    flights = Table(rows, colWidths=[10*mm, 104*mm, 36*mm, 42*mm, 18*mm, 18*mm, 18*mm, 24*mm], repeatRows=1)
    flights.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("FONTSIZE", (0,0), (-1,-1), 6.5), ("FONTNAME", (0,0), (-1,-1), "VinsReport")]))
    story.append(flights)
    SimpleDocTemplate(str(output), pagesize=landscape(A4), leftMargin=8*mm, rightMargin=8*mm, topMargin=8*mm, bottomMargin=8*mm).build(story)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=ROOT / "suites" / "vins-mono-square-250-2k-pose-graph-42.json")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=ROOT / "logs",
    )
    parser.add_argument("--json", type=Path, default=PARENT / "output" / "json" / "vins-square-250-2k-pose-graph-campaign.json")
    parser.add_argument("--pdf", type=Path, default=PARENT / "output" / "pdf" / "vins-square-250-2k-pose-graph-campaign.pdf")
    args = parser.parse_args()
    report = build(args.suite.resolve(), args.evidence_root.resolve())
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    create_pdf(report, args.pdf)


if __name__ == "__main__":
    main()
