import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from automail.pipeline import drafts as dm

PROJECT_ID = "test-project"


def test_get_live_source_requires_project_id():
    with pytest.raises(ValueError, match="project_id is required"):
        dm.get_live_source()


def test_get_draft_source_requires_project_id():
    with pytest.raises(ValueError, match="project_id is required"):
        dm.get_draft_source()


def test_get_live_source_returns_pb_source():
    src = dm.get_live_source("proj-1", tenant_id="tenant-1")
    assert src.project_id == "proj-1"
    assert src.mode == "live"
    assert src.tenant_id == "tenant-1"


def test_get_draft_source_returns_pb_source():
    src = dm.get_draft_source("proj-1", tenant_id="tenant-1")
    assert src.project_id == "proj-1"
    assert src.mode == "draft"
    assert src.tenant_id == "tenant-1"


def test_ensure_draft_exists_initializes_pb_pipeline():
    with patch.object(dm, "ensure_project_pipeline") as ensure_project_pipeline:
        dm.ensure_draft_exists(PROJECT_ID, tenant_id="tenant-1")

    ensure_project_pipeline.assert_called_once_with(PROJECT_ID, tenant_id="tenant-1")


def test_ensure_draft_exists_without_project_is_noop():
    with patch.object(dm, "ensure_project_pipeline") as ensure_project_pipeline:
        dm.ensure_draft_exists()
    ensure_project_pipeline.assert_not_called()


def test_publish_replaces_live_from_draft():
    with patch.object(dm, "replace_live_from_draft") as replace_live_from_draft:
        dm.publish(PROJECT_ID, tenant_id="tenant-1")
    replace_live_from_draft.assert_called_once_with(PROJECT_ID, tenant_id="tenant-1")


def test_publish_requires_project_id():
    with pytest.raises(ValueError, match="project_id is required"):
        dm.publish()


def test_has_unpublished_changes_delegates_to_pb_store():
    with patch.object(dm, "has_unpublished_project_changes", return_value=True) as has_changes:
        assert dm.has_unpublished_changes(PROJECT_ID, tenant_id="tenant-1") is True
    has_changes.assert_called_once_with(PROJECT_ID, tenant_id="tenant-1")


def test_has_unpublished_changes_without_project_is_false():
    with patch.object(dm, "has_unpublished_project_changes") as has_changes:
        assert dm.has_unpublished_changes() is False
    has_changes.assert_not_called()
