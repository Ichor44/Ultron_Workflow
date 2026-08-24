"""Optimized proposal system with atomic operations and efficient diffing.

Provides high-performance proposal management with:
- Atomic file writes (temp + rename)
- Efficient JSON storage with caching
- Fast diff computation
"""

import difflib
import json
import os
import uuid
import threading
import time
from typing import Any, Dict, List, Optional

PROPOSALS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "proposals")

# Proposal cache
_proposals_cache: Optional[Dict[str, Dict[str, Any]]] = None
_cache_lock: threading.RLock = threading.RLock()
_cache_timestamp: float = 0.0
_cache_ttl: float = 5.0  # Cache for 5 seconds


def ensure_dirs() -> None:
    """Ensure the proposals directory exists."""
    os.makedirs(PROPOSALS_DIR, exist_ok=True)


def _queue_path() -> str:
    """Get the path to the proposals queue file.
    
    Returns:
        Full path to queue.json.
    """
    return os.path.join(PROPOSALS_DIR, "queue.json")


def _invalidate_cache() -> None:
    """Invalidate the proposals cache."""
    with _cache_lock:
        global _proposals_cache, _cache_timestamp
        _proposals_cache = None
        _cache_timestamp = 0.0


def _load_raw() -> Dict[str, Dict[str, Any]]:
    """Load proposals from disk.
    
    Returns:
        Dictionary of proposals keyed by ID.
    """
    ensure_dirs()
    path: str = _queue_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _save_raw(data: Dict[str, Dict[str, Any]]) -> None:
    """Save proposals to disk atomically.
    
    Args:
        data: Proposals dictionary to save.
    """
    ensure_dirs()
    path: str = _queue_path()
    tmp_path: str = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def load_all() -> Dict[str, Dict[str, Any]]:
    """Load all proposals with caching.
    
    Returns:
        Dictionary of proposals keyed by ID.
    """
    global _proposals_cache, _cache_timestamp
    with _cache_lock:
        now: float = time.time()
        if _proposals_cache is not None and (now - _cache_timestamp) < _cache_ttl:
            return _proposals_cache
        _proposals_cache = _load_raw()
        _cache_timestamp = now
        return _proposals_cache


def save_all(data: Dict[str, Dict[str, Any]]) -> None:
    """Save all proposals to disk and invalidate cache.
    
    Args:
        data: Proposals dictionary to save.
    """
    _save_raw(data)
    _invalidate_cache()


class Proposal:
    """Represents a proposed change to the system."""
    
    __slots__ = ('id', 'file_path', 'old_content', 'new_content', 
                 'change_type', 'explanation', 'title', 'status')
    
    def __init__(
        self,
        file_path: str,
        old_content: str,
        new_content: str,
        change_type: str,
        explanation: str,
        title: str = ""
    ) -> None:
        """Initialize a Proposal.
        
        Args:
            file_path: Path to the file being modified.
            old_content: Original content of the file.
            new_content: Proposed new content.
            change_type: Type of change (create, edit, delete).
            explanation: Human-readable explanation of the change.
            title: Optional title for the proposal.
        """
        self.id: str = uuid.uuid4().hex[:8]
        self.file_path: str = file_path
        self.old_content: str = old_content or ""
        self.new_content: str = new_content or ""
        self.change_type: str = change_type
        self.explanation: str = explanation
        self.title: str = title
        self.status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        """Convert proposal to dictionary.
        
        Returns:
            Dictionary representation of the proposal.
        """
        return {
            "id": self.id,
            "file_path": self.file_path,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "change_type": self.change_type,
            "explanation": self.explanation,
            "title": self.title,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Proposal':
        """Create a Proposal from a dictionary.
        
        Args:
            d: Dictionary containing proposal data.
            
        Returns:
            Proposal instance.
        """
        p: Proposal = cls(d["file_path"], d["old_content"], d["new_content"], d["change_type"], d["explanation"], d.get("title", ""))
        p.id = d["id"]
        p.status = d["status"]
        return p

    def diff(self) -> str:
        """Compute unified diff between old and new content.
        
        Returns:
            Unified diff string.
        """
        old_lines: List[str] = self.old_content.splitlines(keepends=True)
        new_lines: List[str] = self.new_content.splitlines(keepends=True)
        return "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile="a/" + self.file_path,
            tofile="b/" + self.file_path,
            lineterm="",
        ))

    def write_file(self) -> None:
        """Write the new content to the file atomically."""
        os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
        # Atomic write
        tmp_path: str = self.file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(self.new_content)
        os.replace(tmp_path, self.file_path)
        self.status = "applied"


def create_proposal(
    file_path: str,
    old_content: str,
    new_content: str,
    change_type: str,
    explanation: str,
    title: str = ""
) -> Proposal:
    """Create a new proposal.
    
    Args:
        file_path: Path to the file being modified.
        old_content: Original content of the file.
        new_content: Proposed new content.
        change_type: Type of change (create, edit, delete).
        explanation: Human-readable explanation of the change.
        title: Optional title for the proposal.
        
    Returns:
        Created Proposal instance.
    """
    ensure_dirs()
    p: Proposal = Proposal(file_path, old_content, new_content, change_type, explanation, title)
    data: Dict[str, Dict[str, Any]] = load_all()
    data[p.id] = p.to_dict()
    save_all(data)
    return p


def get_proposal(pid: str) -> Optional[Proposal]:
    """Get a proposal by ID.
    
    Args:
        pid: Proposal ID.
        
    Returns:
        Proposal instance, or None if not found.
    """
    data: Dict[str, Dict[str, Any]] = load_all()
    if pid in data:
        return Proposal.from_dict(data[pid])
    return None


def update_proposal(p: Proposal) -> None:
    """Update a proposal's status.
    
    Args:
        p: Proposal instance to update.
    """
    data: Dict[str, Dict[str, Any]] = load_all()
    data[p.id] = p.to_dict()
    save_all(data)


def pending_proposals() -> List[Proposal]:
    """Get all pending proposals.
    
    Returns:
        List of pending Proposal instances.
    """
    return [Proposal.from_dict(d) for d in load_all().values() if d["status"] == "pending"]


def all_proposals() -> List[Proposal]:
    """Get all proposals.
    
    Returns:
        List of all Proposal instances.
    """
    return [Proposal.from_dict(d) for d in load_all().values()]


def complete_proposal(
    pid: str,
    status: str = "approved",
    write: bool = True
) -> Optional[Proposal]:
    """Complete a proposal - write file and update status.
    
    Args:
        pid: Proposal ID.
        status: New status (approved, rejected, applied).
        write: If True, write the file when approved.
        
    Returns:
        Updated Proposal, or None if not found.
    """
    p: Optional[Proposal] = get_proposal(pid)
    if p is None:
        return None
    
    p.status = status
    if write and status == "approved":
        p.write_file()
    
    update_proposal(p)
    return p


def clear_cache() -> None:
    """Manually clear the proposals cache."""
    _invalidate_cache()