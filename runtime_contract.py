"""Fail-closed перевірки фактичного runtime для кваліфікаційних звітів."""

from __future__ import annotations


def evaluate_ardupilot(report, requirement):
    expected_version = str(requirement.get("version", ""))
    expected_commit = str(requirement.get("source_commit", ""))
    module = (report.get("module_versions") or {}).get("ArduCopter SITL") or {}
    actual_version = str(module.get("firmware_version", ""))
    actual_commit = str(module.get("source_commit", ""))
    expected_binary_sha256 = str(module.get("binary_sha256", ""))
    actual_binary_sha256 = str(module.get("actual_binary_sha256", ""))
    failures = []
    if actual_version != expected_version:
        failures.append("ARDUPILOT_VERSION_MISMATCH")
    if actual_commit != expected_commit:
        failures.append("ARDUPILOT_SOURCE_COMMIT_MISMATCH")
    if not expected_binary_sha256 or actual_binary_sha256 != expected_binary_sha256:
        failures.append("ARDUPILOT_BINARY_SHA256_MISMATCH")
    return {
        "passed": not failures,
        "failures": failures,
        "expected": {
            "version": expected_version,
            "source_commit": expected_commit,
            "binary_sha256": expected_binary_sha256,
        },
        "actual": {
            "version": actual_version,
            "source_commit": actual_commit,
            "binary_sha256": actual_binary_sha256,
        },
    }
