from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from campaign_lib import (  # noqa: E402
    _manual_test_checklist,
    create_campaign_state,
    derive_run_status,
    expand_manifest,
    merge_manifest_into_state,
    normalize_stage_presets,
)


def test_expand_manifest_builds_repeatable_run_matrix() -> None:
    temp_dir = PROJECT_ROOT / "test_runs" / "campaigns" / f"_pytest_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = temp_dir / "campaign.yaml"
    manifest = {
        "campaign": {"id": "demo-campaign", "title": "Demo"},
        "defaults": {
            "presets": [1000],
            "modes": [0, 1],
            "stage_presets": {"pim": 1000, "corrector": 1003},
            "repeat": 2,
            "timeout_sec": 240,
            "nifi_validate": True,
        },
        "cases": [
            {
                "id": "currency-http-to-file",
                "query": "Получай курсы валют и записывай их в файл.",
                "manual_nifi_required": True,
            }
        ],
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    try:
        expanded = expand_manifest(manifest, manifest_path)

        assert expanded["campaign_id"] == "demo-campaign"
        assert len(expanded["runs"]) == 4
        first = expanded["runs"][0]
        assert first["stage_presets"] == {"pim": 1000, "corrector": 1003}
        assert first["timeout_sec"] == 240
        assert first["manual_nifi_required"] is True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_normalize_stage_presets_requires_shared_corrector() -> None:
    with pytest.raises(ValueError):
        normalize_stage_presets({"error_corrector": 1003, "nifi_corrector": 1004})


@pytest.mark.parametrize(
    ("run_record", "payload", "expected"),
    [
        (
            {"nifi_validate": True, "manual_nifi_required": False, "requires_user_input": False},
            {"success": False},
            "failed_generation",
        ),
        (
            {"nifi_validate": True, "manual_nifi_required": False, "requires_user_input": False},
            {"success": True, "nifi_import": {"success": False, "error_count": 0}},
            "failed_import",
        ),
        (
            {"nifi_validate": True, "manual_nifi_required": False, "requires_user_input": True},
            {"success": True, "nifi_import": {"success": True, "error_count": 0}},
            "needs_user_input",
        ),
        (
            {"nifi_validate": True, "manual_nifi_required": True, "requires_user_input": False},
            {"success": True, "nifi_import": {"success": True, "error_count": 0}},
            "needs_nifi_manual_test",
        ),
        (
            {"nifi_validate": False, "manual_nifi_required": False, "requires_user_input": False},
            {"success": True},
            "completed",
        ),
    ],
)
def test_derive_run_status(run_record: dict, payload: dict, expected: str) -> None:
    assert derive_run_status(run_record, payload) == expected


def test_merge_manifest_into_state_adds_missing_mode() -> None:
    temp_dir = PROJECT_ROOT / "test_runs" / "campaigns" / f"_pytest_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = temp_dir / "campaign.yaml"
    base_manifest = {
        "campaign": {"id": "demo-campaign", "title": "Demo"},
        "defaults": {
            "presets": [1000],
            "modes": [0, 1, 3],
            "stage_presets": {"pim": 1000, "corrector": 1003},
        },
        "cases": [{"id": "case-a", "query": "test query"}],
    }
    manifest_path.write_text(
        yaml.safe_dump(base_manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    try:
        state = create_campaign_state(base_manifest, manifest_path)
        assert len(state["run_order"]) == 3

        upgraded_manifest = {
            **base_manifest,
            "defaults": {
                **base_manifest["defaults"],
                "modes": [0, 1, 2, 3],
            },
        }
        result = merge_manifest_into_state(state, upgraded_manifest, manifest_path)

        assert len(result["added_run_ids"]) == 1
        assert len(state["run_order"]) == 4
        assert any("__m2__" in run_id for run_id in result["added_run_ids"])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_manual_checklist_is_extracted_from_run_metadata() -> None:
    run = {
        "extra_metadata": {
            "manual_test_checklist": [
                "Импортировать flow в NiFi.",
                "Проверить запуск.",
            ]
        }
    }
    assert _manual_test_checklist(run) == [
        "Импортировать flow в NiFi.",
        "Проверить запуск.",
    ]
