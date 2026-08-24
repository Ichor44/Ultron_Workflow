"""
Core Ultron Sub-Bots classes.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import logging


logger = logging.getLogger(__name__)


def find_firecrawl_cli() -> Optional[str]:
    """Find the Firecrawl CLI executable path. Returns None if not found."""
    # Check if firecrawl is in PATH first (most reliable)
    firecrawl_in_path = shutil.which("firecrawl")
    if firecrawl_in_path:
        return firecrawl_in_path

    # Check common installation locations
    candidates: List[Path] = []

    if sys.platform == "win32":
        # On Windows, check npm global bin folder
        npm_bin = Path(os.path.expandvars(r"%APPDATA%\npm"))
        if npm_bin.exists():
            candidates.extend([
                npm_bin / "firecrawl.cmd",
                npm_bin / "firecrawl.ps1",
                npm_bin / "firecrawl.exe",
                npm_bin / "firecrawl",
            ])
        # Also check local node_modules/.bin
        local_bin = Path.cwd() / "node_modules" / ".bin" / "firecrawl.cmd"
        candidates.append(local_bin)
    else:
        # Unix-like: check common locations
        candidates.extend([
            Path("/usr/local/bin/firecrawl"),
            Path("/opt/homebrew/bin/firecrawl"),
            Path.home() / ".npm-global" / "bin" / "firecrawl",
        ])

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    return None


def ensure_firecrawl_available(firecrawl_cli: Optional[str] = None) -> str:
    """Ensure Firecrawl CLI is available, raise informative error if not."""
    cli_path = firecrawl_cli or find_firecrawl_cli()
    if not cli_path:
        raise RuntimeError(
            "Firecrawl CLI not found. Please install it with:\n"
            "  npm install -g firecrawl\n"
            "Or ensure it's in your PATH."
        )
    return cli_path


class TaskStatus(Enum):
    """Status of a scraping task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScrapingTask:
    """A single scraping task to be executed by a sub-bot."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    task_type: str = "scrape"
    urls: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional["TaskResult"] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.name:
            self.name = f"{self.task_type}_{self.id}"


@dataclass
class TaskResult:
    """Result of a completed scraping task."""
    task_id: str
    success: bool
    data: Any = None
    raw_output: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0
    urls_processed: int = 0
    credits_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "data": self.data,
            "raw_output": self.raw_output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "urls_processed": self.urls_processed,
            "credits_used": self.credits_used,
            "metadata": self.metadata,
        }


class SubBot(ABC):
    """Base class for all sub-bots. Each sub-bot handles a specific type of task."""
    
    def __init__(self, bot_id: str, name: str, config: Optional[Dict[str, Any]] = None):
        self.bot_id = bot_id
        self.name = name
        self.config = config or {}
        self._running = False
        self._lock = threading.Lock()
    
    @abstractmethod
    def execute(self, task: ScrapingTask) -> TaskResult:
        """Execute a single task. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    def can_handle(self, task_type: str) -> bool:
        """Check if this sub-bot can handle the given task type."""
        pass
    
    def validate_task(self, task: ScrapingTask) -> bool:
        """Validate if the task has required parameters. Override in subclasses."""
        return True
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)


class UltronCore:
    """Core engine for managing sub-bots and executing tasks in parallel."""
    
    def __init__(
        self,
        max_workers: int = 4,
        firecrawl_cli: Optional[str] = None,
        default_timeout: int = 120,
        output_dir: str = ".firecrawl/output",
    ):
        self.max_workers = max_workers
        self.firecrawl_cli = ensure_firecrawl_available(firecrawl_cli)
        self.default_timeout = default_timeout
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._sub_bots: Dict[str, SubBot] = {}
        self._task_queue: List[ScrapingTask] = []
        self._completed_tasks: Dict[str, TaskResult] = {}
        self._running_tasks: Dict[str, ScrapingTask] = {}
        self._lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._callbacks: Dict[str, List[Callable]] = {
            "task_started": [],
            "task_completed": [],
            "task_failed": [],
            "all_completed": [],
        }
    
    def register_bot(self, bot: SubBot) -> None:
        """Register a sub-bot with the core."""
        with self._lock:
            self._sub_bots[bot.bot_id] = bot
    
    def unregister_bot(self, bot_id: str) -> bool:
        """Unregister a sub-bot."""
        with self._lock:
            if bot_id in self._sub_bots:
                del self._sub_bots[bot_id]
                return True
            return False
    
    def get_bot(self, bot_id: str) -> Optional[SubBot]:
        """Get a sub-bot by ID."""
        return self._sub_bots.get(bot_id)
    
    def list_bots(self) -> List[SubBot]:
        """List all registered sub-bots."""
        return list(self._sub_bots.values())
    
    def add_task(self, task: ScrapingTask) -> str:
        """Add a task to the queue."""
        with self._lock:
            self._task_queue.append(task)
        return task.id
    
    def add_tasks(self, tasks: List[ScrapingTask]) -> List[str]:
        """Add multiple tasks to the queue."""
        return [self.add_task(t) for t in tasks]
    
    def _find_bot_for_task(self, task: ScrapingTask) -> Optional[SubBot]:
        """Find a sub-bot that can handle the task type."""
        for bot in self._sub_bots.values():
            if bot.can_handle(task.task_type):
                return bot
        return None
    
    def _execute_task(self, task: ScrapingTask) -> TaskResult:
        """Execute a single task with the appropriate sub-bot."""
        bot = self._find_bot_for_task(task)
        if not bot:
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"No sub-bot available for task type: {task.task_type}",
            )
        
        if not bot.validate_task(task):
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Task validation failed for bot: {bot.name}",
            )
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._running_tasks[task.id] = task
        
        # Fire callbacks
        for cb in self._callbacks["task_started"]:
            try:
                cb(task)
            except Exception:
                pass
        
        start_time = datetime.now()
        try:
            result = bot.execute(task)
            duration = (datetime.now() - start_time).total_seconds() * 1000
            result.duration_ms = duration
            result.task_id = task.id
            
            task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.result = result
            
            if result.success:
                for cb in self._callbacks["task_completed"]:
                    try:
                        cb(task, result)
                    except Exception:
                        pass
            else:
                for cb in self._callbacks["task_failed"]:
                    try:
                        cb(task, result)
                    except Exception:
                        pass
                        
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            result = TaskResult(
                task_id=task.id,
                success=False,
                error=str(e),
                duration_ms=duration,
            )
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.result = result
            task.error = str(e)
            
            for cb in self._callbacks["task_failed"]:
                try:
                    cb(task, result)
                except Exception:
                    pass
        
        with self._lock:
            self._completed_tasks[task.id] = result
            if task.id in self._running_tasks:
                del self._running_tasks[task.id]
        
        return result
    
    def run_parallel(self, tasks: Optional[List[ScrapingTask]] = None) -> List[TaskResult]:
        """Run tasks in parallel using thread pool."""
        if tasks:
            self.add_tasks(tasks)
        
        if not self._task_queue:
            return []
        
        # Create executor if not exists
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        # Submit all tasks
        future_to_task = {}
        for task in self._task_queue:
            if task.status == TaskStatus.PENDING:
                future = self._executor.submit(self._execute_task, task)
                future_to_task[future] = task
        
        # Clear queue
        self._task_queue = [t for t in self._task_queue if t.status != TaskStatus.PENDING]
        
        # Collect results
        results = []
        for future in as_completed(future_to_task):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                task = future_to_task[future]
                result = TaskResult(
                    task_id=task.id,
                    success=False,
                    error=f"Execution error: {str(e)}",
                )
                results.append(result)
        
        # Fire all completed callback
        for cb in self._callbacks["all_completed"]:
            try:
                cb(results)
            except Exception:
                pass
        
        return results
    
    async def run_parallel_async(self, tasks: Optional[List[ScrapingTask]] = None) -> List[TaskResult]:
        """Run tasks in parallel using asyncio."""
        if tasks:
            self.add_tasks(tasks)
        
        if not self._task_queue:
            return []
        
        # Run in thread pool via asyncio
        loop = asyncio.get_event_loop()
        tasks_to_run = [t for t in self._task_queue if t.status == TaskStatus.PENDING]
        self._task_queue = [t for t in self._task_queue if t.status != TaskStatus.PENDING]
        
        # Submit to thread pool
        futures = [
            loop.run_in_executor(None, self._execute_task, task)
            for task in tasks_to_run
        ]
        
        results = await asyncio.gather(*futures, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task = tasks_to_run[i]
                processed_results.append(TaskResult(
                    task_id=task.id,
                    success=False,
                    error=str(result),
                ))
            else:
                processed_results.append(result)
        
        # Fire all completed callback
        for cb in self._callbacks["all_completed"]:
            try:
                cb(processed_results)
            except Exception:
                pass
        
        return processed_results
    
    def on(self, event: str, callback: Callable) -> None:
        """Register an event callback."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def off(self, event: str, callback: Callable) -> None:
        """Unregister an event callback."""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
    
    def get_results(self) -> Dict[str, TaskResult]:
        """Get all completed task results."""
        return self._completed_tasks.copy()
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get status of a specific task."""
        # Check running tasks
        if task_id in self._running_tasks:
            return self._running_tasks[task_id].status
        # Check completed tasks
        if task_id in self._completed_tasks:
            return TaskStatus.COMPLETED if self._completed_tasks[task_id].success else TaskStatus.FAILED
        # Check queue
        for task in self._task_queue:
            if task.id == task_id:
                return task.status
        return None
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        # Check queue
        for i, task in enumerate(self._task_queue):
            if task.id == task_id:
                task.status = TaskStatus.CANCELLED
                self._task_queue.pop(i)
                return True
        # Check running (can't actually cancel thread, but mark it)
        if task_id in self._running_tasks:
            self._running_tasks[task_id].status = TaskStatus.CANCELLED
            return True
        return False
    
    def shutdown(self) -> None:
        """Shutdown the core and clean up resources."""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False
    
    def run_firecrawl_command(
        self,
        command: str,
        args: List[str],
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess:
        """Run a Firecrawl CLI command."""
        cmd = [self.firecrawl_cli, command] + args
        # Use UTF-8 encoding to handle Unicode output (emojis, etc.)
        # Avoid shell=True for security - firecrawl CLI should be directly executable
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or self.default_timeout,
            encoding="utf-8",
            errors="replace",
        )
    
    def parse_firecrawl_output(self, output: str) -> Any:
        """Parse Firecrawl CLI output (JSON or text)."""
        output = output.strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # Try to extract JSON from output that might have extra text
            # Find first { and last }
            start = output.find('{')
            end = output.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(output[start:end+1])
                except json.JSONDecodeError:
                    pass
            return output

    def run_with_retry(
        self,
        command: str,
        args: List[str],
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess:
        """Run a Firecrawl command with exponential backoff retry."""
        last_error = None
        for attempt in range(max_retries):
            try:
                result = self.run_firecrawl_command(command, args, timeout)
                if result.returncode == 0:
                    return result
                last_error = result.stderr
            except subprocess.TimeoutExpired as e:
                last_error = f"Timeout after {timeout or self.default_timeout}s"
            except Exception as e:
                last_error = str(e)
            
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Firecrawl command failed (attempt {attempt + 1}/{max_retries}): {last_error}. Retrying in {delay}s...")
                time.sleep(delay)
        
        # All retries failed
        return subprocess.CompletedProcess(
            args=[self.firecrawl_cli, command] + args,
            returncode=1,
            stdout="",
            stderr=last_error or "Max retries exceeded",
        )