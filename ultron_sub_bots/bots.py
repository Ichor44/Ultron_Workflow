"""
Sub-bot implementations for different scraping tasks.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import SubBot, ScrapingTask, TaskResult, UltronCore


class ScrapeBot(SubBot):
    """Sub-bot for scraping individual URLs."""
    
    def __init__(self, bot_id: str = "scrape_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "ScrapeBot", config)
        config = config or {}
        self.formats = config.get("formats", ["markdown"])
        self.only_main_content = config.get("only_main_content", True)
        self.wait_for = config.get("wait_for", 0)
        self.include_tags = config.get("include_tags", [])
        self.exclude_tags = config.get("exclude_tags", [])
        self.redact_pii = config.get("redact_pii", False)
    
    def can_handle(self, task_type: str) -> bool:
        return task_type in ("scrape", "extract")
    
    def validate_task(self, task: ScrapingTask) -> bool:
        return len(task.urls) > 0
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        urls = task.urls
        all_results = []
        total_credits = 0
        
        for url in urls:
            args = [url, "--json"]
            
            # Format options
            if len(self.formats) == 1:
                args.extend(["-f", self.formats[0]])
            elif len(self.formats) > 1:
                args.extend(["-f", ",".join(self.formats)])
            
            if self.only_main_content:
                args.append("--only-main-content")
            
            if self.wait_for > 0:
                args.extend(["--wait-for", str(self.wait_for)])
            
            if self.include_tags:
                args.extend(["--include-tags", ",".join(self.include_tags)])
            
            if self.exclude_tags:
                args.extend(["--exclude-tags", ",".join(self.exclude_tags)])
            
            if self.redact_pii:
                args.append("--redact-pii")
            
            # Run command with retry
            result = core.run_with_retry("scrape", args)
            
            if result.returncode != 0:
                return TaskResult(
                    task_id=task.id,
                    success=False,
                    error=f"Firecrawl scrape failed: {result.stderr}",
                    urls_processed=len(all_results),
                )
            
            # Parse result from stdout (JSON)
            try:
                data = core.parse_firecrawl_output(result.stdout)
                all_results.append(data)
            except Exception as e:
                all_results.append({"raw": result.stdout, "parse_error": str(e)})
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data=all_results if len(all_results) > 1 else all_results[0],
            urls_processed=len(urls),
            metadata={"output_files": []},
        )


class CrawlBot(SubBot):
    """Sub-bot for crawling entire websites or sections."""
    
    def __init__(self, bot_id: str = "crawl_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "CrawlBot", config)
        config = config or {}
        self.max_depth = config.get("max_depth", 3)
        self.limit = config.get("limit", 100)
        self.include_paths = config.get("include_paths", [])
        self.exclude_paths = config.get("exclude_paths", [])
        self.delay = config.get("delay", 0)
        self.max_concurrency = config.get("max_concurrency", 5)
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "crawl"
    
    def validate_task(self, task: ScrapingTask) -> bool:
        return len(task.urls) == 1  # Crawl typically starts from one URL
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        url = task.urls[0]
        args = [url]
        
        # Only add --wait if not in CI/automated environment
        if os.environ.get("CI") != "true":
            args.append("--wait")
        args.append("--progress")
        
        args.extend(["--max-depth", str(self.max_depth)])
        args.extend(["--limit", str(self.limit)])
        
        if self.include_paths:
            args.extend(["--include-paths", ",".join(self.include_paths)])
        
        if self.exclude_paths:
            args.extend(["--exclude-paths", ",".join(self.exclude_paths)])
        
        if self.delay > 0:
            args.extend(["--delay", str(self.delay)])
        
        if self.max_concurrency > 0:
            args.extend(["--max-concurrency", str(self.max_concurrency)])
        
        output_file = core.output_dir / f"crawl_{task.id}.json"
        args.extend(["-o", str(output_file)])
        
        result = core.run_with_retry("crawl", args)
        
        if result.returncode != 0:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Firecrawl crawl failed: {result.stderr}",
            )
        
        try:
            data = core.parse_firecrawl_output(result.stdout)
        except Exception:
            data = {"raw": result.stdout}
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data=data,
            urls_processed=data.get("total", 0) if isinstance(data, dict) else 0,
            metadata={"output_file": str(output_file)},
        )


class SearchBot(SubBot):
    """Sub-bot for web search with content extraction."""
    
    def __init__(self, bot_id: str = "search_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "SearchBot", config)
        config = config or {}
        self.num_results = config.get("num_results", 10)
        self.search_type = config.get("search_type", "auto")  # auto, fast, deep
        self.live_crawl = config.get("live_crawl", "fallback")  # fallback, preferred
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "search"
    
    def validate_task(self, task: ScrapingTask) -> bool:
        # For search, the query is in params
        return "query" in task.params
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        query = task.params.get("query", "")
        if not query:
            return TaskResult(task_id=task.id, success=False, error="No search query provided")
        
        args = [query, "--json"]
        args.extend(["--limit", str(self.num_results)])
        
        # Note: search_type and livecrawl options may not exist in current Firecrawl CLI
        # args.extend(["--type", self.search_type])
        # args.extend(["--livecrawl", self.live_crawl])
        
        result = core.run_with_retry("search", args)
        
        if result.returncode != 0:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Firecrawl search failed: {result.stderr}",
            )
        
        try:
            data = core.parse_firecrawl_output(result.stdout)
        except Exception:
            data = {"raw": result.stdout}
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data=data,
            urls_processed=len(data.get("data", {}).get("web", [])) if isinstance(data, dict) else 0,
            metadata={"query": query},
        )


class MapBot(SubBot):
    """Sub-bot for mapping website URLs."""
    
    def __init__(self, bot_id: str = "map_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "MapBot", config)
        config = config or {}
        self.search = config.get("search", "")
        self.limit = config.get("limit", 5000)
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "map"
    
    def validate_task(self, task: ScrapingTask) -> bool:
        return len(task.urls) == 1
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        url = task.urls[0]
        args = [url, "--limit", str(self.limit)]
        
        if self.search:
            args.extend(["--search", self.search])
        
        output_file = core.output_dir / f"map_{task.id}.json"
        args.extend(["-o", str(output_file)])
        
        result = core.run_with_retry("map", args)
        
        if result.returncode != 0:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Firecrawl map failed: {result.stderr}",
            )
        
        try:
            data = core.parse_firecrawl_output(result.stdout)
        except Exception:
            data = {"raw": result.stdout}
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data=data,
            urls_processed=len(data.get("urls", [])) if isinstance(data, dict) else 0,
            metadata={"output_file": str(output_file)},
        )


class InteractBot(SubBot):
    """Sub-bot for interactive browser sessions."""
    
    def __init__(self, bot_id: str = "interact_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "InteractBot", config)
        config = config or {}
        self.actions = config.get("actions", [])
        self.wait_for = config.get("wait_for", 3000)
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "interact"
    
    def validate_task(self, task: ScrapingTask) -> bool:
        return len(task.urls) == 1 and ("actions" in task.params or "prompt" in task.params)
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        url = task.urls[0]
        actions = task.params.get("actions", self.actions)
        
        args = [url]
        args.extend(["--wait-for", str(self.wait_for)])
        
        # For interact, we need to pass actions as a JSON file or prompt
        # Firecrawl interact uses natural language prompts
        prompt = task.params.get("prompt", "")
        if prompt:
            args.extend(["--prompt", prompt])
        elif actions:
            # If actions provided but no prompt, create a prompt from actions
            action_str = "; ".join(str(a) for a in actions)
            args.extend(["--prompt", action_str])
        
        output_file = core.output_dir / f"interact_{task.id}.json"
        args.extend(["-o", str(output_file)])
        
        result = core.run_with_retry("interact", args)
        
        if result.returncode != 0:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Firecrawl interact failed: {result.stderr}",
            )
        
        try:
            data = core.parse_firecrawl_output(result.stdout)
        except Exception:
            data = {"raw": result.stdout}
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data=data,
            metadata={"output_file": str(output_file), "actions": actions},
        )


class MonitorBot(SubBot):
    """Sub-bot for monitoring website changes."""
    
    def __init__(self, bot_id: str = "monitor_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "MonitorBot", config)
        config = config or {}
        self.webhook_url = config.get("webhook_url", "")
        self.email = config.get("email", "")
        self.schedule = config.get("schedule", "0 * * * *")  # Hourly by default
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "monitor"
    
    def validate_task(self, task: ScrapingTask) -> bool:
        return len(task.urls) > 0
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        results = []
        for url in task.urls:
            args = [url]
            
            if self.webhook_url:
                args.extend(["--webhook", self.webhook_url])
            
            if self.email:
                args.extend(["--email", self.email])
            
            args.extend(["--schedule", self.schedule])
            
            output_file = core.output_dir / f"monitor_{task.id}_{len(results)}.json"
            args.extend(["-o", str(output_file)])
            
            result = core.run_with_retry("monitor", args)
            
            if result.returncode != 0:
                results.append({"url": url, "error": result.stderr})
            else:
                try:
                    data = core.parse_firecrawl_output(result.stdout)
                    results.append({"url": url, "monitor": data})
                except Exception:
                    results.append({"url": url, "raw": result.stdout})
        
        return TaskResult(
            task_id=task.id,
            success=all("error" not in r for r in results),
            data=results,
            urls_processed=len(task.urls),
            metadata={"monitors": results},
        )


class DownloadBot(SubBot):
    """Sub-bot for downloading entire websites as local files."""
    
    def __init__(self, bot_id: str = "download_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "DownloadBot", config)
        config = config or {}
        self.formats = config.get("formats", ["markdown"])
        self.max_depth = config.get("max_depth", 3)
        self.limit = config.get("limit", 100)
        self.output_subdir = config.get("output_subdir", "downloads")
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "download"
    
    def validate_task(self, task: ScrapingTask) -> bool:
        return len(task.urls) == 1
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        core: UltronCore = task.metadata.get("core")
        if not core:
            return TaskResult(task_id=task.id, success=False, error="Core reference not provided")
        
        url = task.urls[0]
        args = [url]
        
        if self.formats:
            args.extend(["--format", ",".join(self.formats)])
        
        args.extend(["--max-depth", str(self.max_depth)])
        args.extend(["--limit", str(self.limit)])
        
        output_dir = core.output_dir / self.output_subdir / task.id
        output_dir.mkdir(parents=True, exist_ok=True)
        args.extend(["--output", str(output_dir)])
        
        result = core.run_with_retry("download", args)
        
        if result.returncode != 0:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Firecrawl download failed: {result.stderr}",
            )
        
        try:
            data = core.parse_firecrawl_output(result.stdout)
        except Exception:
            data = {"raw": result.stdout}
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data=data,
            metadata={"output_dir": str(output_dir)},
        )


class ProteinLabBot(SubBot):
    """Sub-bot for protein analysis tasks via the skills.protein_lab module.
    
    Unlike other sub-bots, this bot does NOT require the Firecrawl CLI.
    It lazily imports the skills.protein_lab module and fans entries out
    to protein_lab.run(), one call per entry.
    
    Each entry in task.urls may be either:
      - A structure identifier (PDB ID like "1CRN" or UniProt accession
        like "P01308") -> dispatched with action="download_structure"
      - A raw protein sequence (>=10 chars, mostly standard amino acid
        letters) -> dispatched with the configured/default action
    
    Entries may also come from task.params via the "sequence", "fasta",
    or "queries" keys.
    """
    
    # Standard amino acid alphabet used for sequence classification
    _AA_LETTERS = frozenset("ACDEFGHIKLMNPQRSTVWY")
    # Reserved params keys consumed by the bot itself, never forwarded
    _RESERVED_PARAMS = ("action", "core")
    
    def __init__(self, bot_id: str = "protein_lab_bot", config: Optional[Dict[str, Any]] = None):
        super().__init__(bot_id, "ProteinLabBot", config)
        config = config or {}
        self.default_action = config.get("default_action", "analyze")
        self.output_dir = config.get("output_dir")  # optional
    
    def can_handle(self, task_type: str) -> bool:
        return task_type in ("protein", "protein_lab")
    
    def validate_task(self, task: ScrapingTask) -> bool:
        # Accept explicit URL-style entries OR sequence payloads in params
        if len(task.urls) > 0:
            return True
        return any(k in task.params for k in ("sequence", "fasta", "queries"))
    
    @classmethod
    def _is_identifier(cls, entry: str) -> bool:
        """True if entry looks like a PDB ID (4-char alnum) or UniProt accession (6-10 alnum)."""
        entry = entry.strip()
        if len(entry) == 4 and entry.isalnum():
            return True
        # UniProt-style accessions: 6-10 alnum chars whose letters are
        # uppercase (e.g. "P01308"). Pure digits or lowercase-letter mixes
        # are not identifiers; pure-letter runs of this length are more
        # likely short sequences, but per convention uppercase ones count.
        if 6 <= len(entry) <= 10 and entry.isalnum():
            letters = [c for c in entry if c.isalpha()]
            if not letters:
                return False
            return all(c.isupper() for c in letters)
        return False
    
    @classmethod
    def _is_sequence(cls, entry: str) -> bool:
        """True if entry looks like a raw protein sequence (>=10 chars, mostly amino acid letters)."""
        entry = entry.strip()
        if len(entry) < 10:
            return False
        letters = [c.upper() for c in entry if c.isalpha()]
        if not letters:
            return False
        aa_count = sum(1 for c in letters if c in cls._AA_LETTERS)
        return aa_count / len(letters) >= 0.9
    
    def _collect_entries(self, task: ScrapingTask) -> List[str]:
        """Gather entries from task.urls and sequence-style params."""
        entries: List[str] = [str(u).strip() for u in task.urls if str(u).strip()]
        
        sequence = task.params.get("sequence")
        if isinstance(sequence, str) and sequence.strip():
            entries.append(sequence.strip())
        
        fasta = task.params.get("fasta")
        if isinstance(fasta, str) and fasta.strip():
            # Split FASTA into individual records, keeping raw bodies
            for record in fasta.strip().split(">"):
                body = record.strip()
                if not body:
                    continue
                lines = [ln for ln in body.splitlines() if ln.strip()]
                # Drop header line if present (first line when multi-line record)
                if len(lines) > 1:
                    lines = lines[1:]
                seq_body = "".join(lines).strip()
                if seq_body:
                    entries.append(seq_body)
        
        queries = task.params.get("queries")
        if isinstance(queries, (list, tuple)):
            entries.extend(str(q).strip() for q in queries if str(q).strip())
        elif isinstance(queries, str) and queries.strip():
            entries.append(queries.strip())
        
        return entries
    
    def _import_protein_lab(self):
        """Lazily import skills.protein_lab, ensuring repo root is importable."""
        import sys
        
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        
        from skills import protein_lab
        return protein_lab
    
    def execute(self, task: ScrapingTask) -> TaskResult:
        try:
            protein_lab = self._import_protein_lab()
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Failed to import protein_lab module: {e}",
            )
        
        entries = self._collect_entries(task)
        if not entries:
            return TaskResult(
                task_id=task.id,
                success=False,
                error="No protein entries provided",
            )
        
        # Base kwargs shared across all calls (reserved keys stripped);
        # task-level action override wins over the configured default
        kwargs = {k: v for k, v in task.params.items() if k not in self._RESERVED_PARAMS}
        action_override = task.params.get("action")
        if self.output_dir:
            kwargs.setdefault("output_dir", self.output_dir)
        
        results = []
        try:
            for entry in entries:
                if self._is_identifier(entry):
                    action = "download_structure"
                    call_kwargs = dict(kwargs)
                    call_kwargs["identifier"] = entry
                else:
                    action = action_override or self.default_action
                    call_kwargs = dict(kwargs)
                    call_kwargs["sequence"] = entry
                
                result_str = protein_lab.run(action=action, **call_kwargs)
                results.append((entry, str(result_str)))
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Protein analysis failed: {e}",
                urls_processed=len(results),
            )
        
        return TaskResult(
            task_id=task.id,
            success=True,
            data={"results": results, "count": len(results)},
            urls_processed=len(results),
            metadata={"action_override": action_override} if action_override else {},
        )


# Factory function to create sub-bots
def create_bot(bot_type: str, bot_id: str = None, config: Dict[str, Any] = None) -> SubBot:
    """Factory function to create sub-bots by type."""
    bot_map = {
        "scrape": ScrapeBot,
        "crawl": CrawlBot,
        "search": SearchBot,
        "map": MapBot,
        "interact": InteractBot,
        "monitor": MonitorBot,
        "download": DownloadBot,
        "protein": ProteinLabBot,
        "protein_lab": ProteinLabBot,
    }
    
    if bot_type not in bot_map:
        raise ValueError(f"Unknown bot type: {bot_type}. Available: {list(bot_map.keys())}")
    
    return bot_map[bot_type](bot_id or f"{bot_type}_bot", config)