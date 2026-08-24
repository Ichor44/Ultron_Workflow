"""
Shared fixtures for ultron_sub_bots tests.

All tests mock the Firecrawl CLI detection so they can run without
the actual CLI installed.
"""

import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture: fake Firecrawl CLI path
# ---------------------------------------------------------------------------
FAKE_FIRECRAWL = "/usr/local/bin/firecrawl"


@pytest.fixture(autouse=True)
def _mock_firecrawl_available():
    """Prevent UltronCore.__init__ from failing when Firecrawl CLI is absent."""
    with patch("ultron_sub_bots.core.find_firecrawl_cli", return_value=FAKE_FIRECRAWL):
        yield


@pytest.fixture()
def fake_cli() -> str:
    return FAKE_FIRECRAWL


# ---------------------------------------------------------------------------
# Fixture: a minimal ScrapingTask
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_task():
    from ultron_sub_bots.core import ScrapingTask

    return ScrapingTask(
        name="test_task",
        task_type="scrape",
        urls=["https://example.com"],
        params={},
    )


# ---------------------------------------------------------------------------
# Fixture: a mocked UltronCore (no real subprocess calls)
# ---------------------------------------------------------------------------
@pytest.fixture()
def mock_core():
    """UltronCore with run_firecrawl_command and run_with_retry mocked."""
    from ultron_sub_bots.core import UltronCore

    core = UltronCore.__new__(UltronCore)
    core.max_workers = 2
    core.firecrawl_cli = FAKE_FIRECRAWL
    core.default_timeout = 10
    core.output_dir = Path(".firecrawl/output")
    core._sub_bots = {}
    core._task_queue = []
    core._completed_tasks = {}
    core._running_tasks = {}
    core._lock = MagicMock()
    core._executor = None
    core._callbacks = {
        "task_started": [],
        "task_completed": [],
        "task_failed": [],
        "all_completed": [],
    }
    # Patch run_with_retry and run_firecrawl_command as MagicMock
    core.run_with_retry = MagicMock()
    core.run_firecrawl_command = MagicMock()
    return core


# ---------------------------------------------------------------------------
# Fixture: a successful CompletedProcess
# ---------------------------------------------------------------------------
@pytest.fixture()
def success_result():
    return subprocess.CompletedProcess(
        args=["firecrawl", "scrape", "https://example.com"],
        returncode=0,
        stdout='{"success": true, "data": {"content": "hello"}}',
        stderr="",
    )
