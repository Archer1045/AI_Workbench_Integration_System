"""Pose thumbnail accuracy audit exposure tests."""
from __future__ import annotations

import pose_accuracy


def test_pose_accuracy_api_exposes_status_and_notes(client):
    response = client.get("/api/prompt-agent/pose-presets")
    assert response.status_code == 200
    items = response.json()["items"]

    by_id = {item["id"]: item for item in items}
    assert by_id["group_triangle_three"]["accuracy_status"] == "verified"
    assert by_id["group_mff_side_by_side"]["accuracy_status"] == "needs_rework"
    assert "人数不符" in by_id["group_mff_side_by_side"]["accuracy_notes"]
    assert all(item["accuracy_audit_version"] == pose_accuracy.AUDIT_VERSION for item in items)

    statuses = [item["accuracy_status"] for item in items]
    assert statuses.count("deprecated") == 0
    assert statuses.count("needs_rework") >= len(pose_accuracy.NEEDS_REWORK)
    assert statuses.count("verified") > 300


def test_missing_thumbnails_are_explicitly_marked_for_rework(client):
    response = client.get("/api/prompt-agent/pose-presets")
    items = response.json()["items"]
    missing = [item for item in items if not item["has_image"]]

    assert missing
    assert all(item["accuracy_status"] == "needs_rework" for item in missing)
    assert all("缺少缩略图" in item["accuracy_notes"] for item in missing)
