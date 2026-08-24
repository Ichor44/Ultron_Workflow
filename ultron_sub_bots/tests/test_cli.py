"""
Tests for ultron_sub_bots.cli module.

Covers argument parsing for all commands (scrape, crawl, search, map, batch)
and the main() entry point.
"""

import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from ultron_sub_bots.cli import main, cmd_scrape, cmd_crawl, cmd_search, cmd_map, cmd_batch


# ===================================================================
# Helper: parse arguments for a specific subcommand
# ===================================================================
def parse_args(args_list):
    """Parse CLI args as if running `ultron <subcommand> ...`."""
    with patch("sys.argv", ["ultron"] + args_list):
        import argparse
        # We need to reconstruct the parser to test argument parsing
        # Instead, let's test via main() which builds the parser
        pass


def run_main(args_list, mock_run=None):
    """Run main() with mocked sys.argv and optionally mocked run_parallel."""
    with patch("sys.argv", ["ultron"] + args_list):
        if mock_run is not None:
            with patch("ultron_sub_bots.core.UltronCore.run_parallel", mock_run):
                return main()
        return main()


# ===================================================================
# Scrape command
# ===================================================================
class TestScrapeCommand:
    def test_scrape_no_urls_no_file(self):
        """Should return error when no URLs provided."""
        with patch("sys.argv", ["ultron", "scrape"]):
            result = main()
            assert result == 1

    def test_scrape_with_urls(self):
        with patch("sys.argv", ["ultron", "scrape", "https://example.com"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [
                    TaskResult(task_id="t1", success=True, urls_processed=1)
                ]
                result = main()
                assert result == 0

    def test_scrape_with_file(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://a.com\nhttps://b.com\n")
        with patch("sys.argv", ["ultron", "scrape", "-f", str(url_file)]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_scrape_json_output(self):
        with patch("sys.argv", ["ultron", "-j", "scrape", "https://example.com"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [
                    TaskResult(task_id="t1", success=True, urls_processed=1)
                ]
                result = main()
                assert result == 0

    def test_scrape_format_option(self):
        with patch("sys.argv", ["ultron", "scrape", "https://example.com", "--format", "html,markdown"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_scrape_full_page_flag(self):
        with patch("sys.argv", ["ultron", "scrape", "https://example.com", "--full-page"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0


# ===================================================================
# Crawl command
# ===================================================================
class TestCrawlCommand:
    def test_crawl_with_url(self):
        with patch("sys.argv", ["ultron", "crawl", "https://example.com"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_crawl_with_depth_and_limit(self):
        with patch("sys.argv", ["ultron", "crawl", "https://example.com", "-d", "5", "-l", "100"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0


# ===================================================================
# Search command
# ===================================================================
class TestSearchCommand:
    def test_search_with_query(self):
        with patch("sys.argv", ["ultron", "search", "python testing"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_search_with_num_results(self):
        with patch("sys.argv", ["ultron", "search", "AI trends", "-r", "20"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0


# ===================================================================
# Map command
# ===================================================================
class TestMapCommand:
    def test_map_with_url(self):
        with patch("sys.argv", ["ultron", "map", "https://example.com"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_map_with_search_filter(self):
        with patch("sys.argv", ["ultron", "map", "https://example.com", "-s", "blog"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0


# ===================================================================
# Batch command
# ===================================================================
class TestBatchCommand:
    def test_batch_scrape(self, tmp_path):
        batch_file = tmp_path / "tasks.json"
        batch_file.write_text(json.dumps([
            {"type": "scrape", "urls": ["https://example.com"]},
        ]))
        with patch("sys.argv", ["ultron", "batch", str(batch_file)]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_batch_crawl(self, tmp_path):
        batch_file = tmp_path / "tasks.json"
        batch_file.write_text(json.dumps([
            {"type": "crawl", "url": "https://example.com"},
        ]))
        with patch("sys.argv", ["ultron", "batch", str(batch_file)]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_batch_search(self, tmp_path):
        batch_file = tmp_path / "tasks.json"
        batch_file.write_text(json.dumps([
            {"type": "search", "query": "python testing"},
        ]))
        with patch("sys.argv", ["ultron", "batch", str(batch_file)]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_batch_unknown_type(self, tmp_path):
        batch_file = tmp_path / "tasks.json"
        batch_file.write_text(json.dumps([
            {"type": "unknown", "url": "https://example.com"},
        ]))
        with patch("sys.argv", ["ultron", "batch", str(batch_file)]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = []
                result = main()
                assert result == 0


# ===================================================================
# Global options
# ===================================================================
class TestGlobalOptions:
    def test_workers_option(self):
        with patch("sys.argv", ["ultron", "-w", "8", "scrape", "https://example.com"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0

    def test_json_output_flag(self):
        with patch("sys.argv", ["ultron", "-j", "scrape", "https://example.com"]):
            with patch("ultron_sub_bots.core.UltronCore.run_parallel") as mock_run:
                from ultron_sub_bots.core import TaskResult
                mock_run.return_value = [TaskResult(task_id="t1", success=True)]
                result = main()
                assert result == 0
