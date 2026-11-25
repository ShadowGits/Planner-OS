from unittest.mock import patch

import pytest

from scripts.protect_live_image import canonical_image, protect


PROJECT = "planner-os-502107"
BASE = f"us-docker.pkg.dev/{PROJECT}/gcr.io/planner-os-api"


def test_unresolved_or_foreign_images_cannot_be_protected():
    assert canonical_image(f"gcr.io/{PROJECT}/planner-os-api@sha256:abc", PROJECT) == BASE + "@sha256:abc"
    for image in (BASE + ":latest", "gcr.io/another-project/app@sha256:abc"):
        with pytest.raises(ValueError):
            canonical_image(image, PROJECT)


def test_all_traffic_images_are_protected_before_stale_protection_is_removed():
    responses = [
        {"status": {"traffic": [{"revisionName": "a", "percent": 100}, {"revisionName": "b", "tag": "preview"}]}},
        {"status": {"imageDigest": BASE + "@sha256:aaa"}},
        {"status": {"imageDigest": BASE + "@sha256:bbb"}},
        [{"tag": "x/tags/planner-live-planner-os-api-2"}, {"tag": "x/tags/latest"}, {"tag": "x/tags/build-id"}],
    ]
    with patch("scripts.protect_live_image.read", side_effect=responses), patch("scripts.protect_live_image.subprocess.run") as run:
        protect(PROJECT, "us-central1", "planner-os-api")
    commands = [call.args[0] for call in run.call_args_list]
    assert [command[4] for command in commands] == ["add", "add", "delete"]
    assert commands[0][5] == BASE + "@sha256:aaa"
    assert commands[1][5] == BASE + "@sha256:bbb"
    assert commands[2][5] == BASE + ":planner-live-planner-os-api-2"


def test_failed_revision_resolution_does_not_change_any_tag():
    responses = [
        {"status": {"traffic": [{"revisionName": "a", "percent": 50}, {"revisionName": "b", "percent": 50}]}},
        {"status": {"imageDigest": BASE + "@sha256:aaa"}},
        RuntimeError("read failed"),
    ]
    with patch("scripts.protect_live_image.read", side_effect=responses), patch("scripts.protect_live_image.subprocess.run") as run:
        with pytest.raises(RuntimeError):
            protect(PROJECT, "us-central1", "planner-os-api")
        run.assert_not_called()


def test_deployment_cleanup_deletes_old_images_but_keeps_live_and_recent():
    responses = [
        {"status": {"traffic": [{"revisionName": "a", "percent": 100}]}},
        {"status": {"imageDigest": BASE + "@sha256:live"}},
        [],
        [
            {"package": BASE, "version": "sha256:live", "createTime": "2020-01-01T00:00:00Z"},
            {"package": BASE, "version": "sha256:old", "createTime": "2020-01-01T00:00:00Z"},
            {"package": BASE, "version": "sha256:recent", "createTime": "2099-01-01T00:00:00Z"},
        ],
        [],
    ]
    with patch("scripts.protect_live_image.read", side_effect=responses), patch("scripts.protect_live_image.subprocess.run") as run:
        protect(PROJECT, "us-central1", "planner-os-api", cleanup=True)
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == 2
    assert commands[1][5] == BASE + "@sha256:old"
