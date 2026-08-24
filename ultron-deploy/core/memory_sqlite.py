"""SQLite-based memory management with full-text search and ACID compliance.

Drop-in replacement for JSON-based memory with:
- SQLite database backend (ACID compliant)
- Full-text search (FTS5) for notes and facts
- Thread-safe concurrent access
- Automatic migrations
- Better performance with large datasets
"""

import datetime
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from core.cache import get_cache_manager, monitor

DATA_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH: str = os.path.join(DATA_DIR, "ultron.db")


class MemoryStore:
    """SQLite-backed memory store with full-text search."""
    
    _instance: Optional['MemoryStore'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'MemoryStore':
        """Singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize the memory store."""
        if self._initialized:
            return
        self._initialized = True
        self._local: threading.local = threading.local()
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            os.makedirs(DATA_DIR, exist_ok=True)
            self._local.conn = sqlite3.connect(
                DB_PATH,
                timeout=10.0,
                check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=10000")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn
    
    @contextmanager
    def _transaction(self):
        """Context manager for database transactions."""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._transaction() as conn:
            conn.executescript("""
                -- Facts table
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Notes table
                CREATE TABLE IF NOT EXISTS notes (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Reminders table
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    due TIMESTAMP NOT NULL,
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    done BOOLEAN DEFAULT FALSE,
                    last_notified TIMESTAMP
                );
                
                -- Full-text search indexes
                CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                    key, value, content=facts, content_rowid=rowid
                );
                
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    key, content, content=notes, content_rowid=rowid
                );
                
                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due);
                CREATE INDEX IF NOT EXISTS idx_reminders_done ON reminders(done);
                CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);
                CREATE INDEX IF NOT EXISTS idx_notes_key ON notes(key);
            """)
            
            # Triggers to keep FTS in sync
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                    INSERT INTO facts_fts(rowid, key, value) VALUES (new.rowid, new.key, new.value);
                END;
                
                CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                    INSERT INTO facts_fts(facts_fts, rowid, key, value) VALUES('delete', old.rowid, old.key, old.value);
                END;
                
                CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                    INSERT INTO facts_fts(facts_fts, rowid, key, value) VALUES('delete', old.rowid, old.key, old.value);
                    INSERT INTO facts_fts(rowid, key, value) VALUES (new.rowid, new.key, new.value);
                END;
                
                CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                    INSERT INTO notes_fts(rowid, key, content) VALUES (new.rowid, new.key, new.content);
                END;
                
                CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, key, content) VALUES('delete', old.rowid, old.key, old.content);
                END;
                
                CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                    INSERT INTO notes_fts(notes_fts, rowid, key, content) VALUES('delete', old.rowid, old.key, old.content);
                    INSERT INTO notes_fts(rowid, key, content) VALUES (new.rowid, new.key, new.content);
                END;
            """)
    
    # ==================== FACTS ====================
    
    @monitor("sqlite.remember_fact")
    def remember_fact(self, key: str, value: str) -> str:
        """Store a persistent fact about the user.
        
        Args:
            key: Fact name (e.g., 'user_name', 'preferred_language').
            value: Fact value.
            
        Returns:
            Confirmation message.
        """
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO facts (key, value, updated_at) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET 
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))
        
        get_cache_manager().invalidate('memory')
        return "Noted: %s = %s" % (key, value)
    
    @monitor("sqlite.recall_fact")
    def recall_fact(self, key: Optional[str] = None) -> str:
        """Recall a stored fact about the user.
        
        Args:
            key: Fact name to recall, or None to list all facts.
            
        Returns:
            Fact value or JSON of all facts.
        """
        conn = self._get_conn()
        
        if not key:
            rows = conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
            if not rows:
                return "I don't have any stored facts about you yet."
            facts = {row['key']: row['value'] for row in rows}
            return json.dumps(facts, indent=2)
        
        row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        if row:
            return row['value']
        return "I don't know '%s' yet. Tell me with remember_fact." % key
    
    # ==================== NOTES ====================
    
    @monitor("sqlite.save_note")
    def save_note(self, key: str, value: str) -> str:
        """Save a free-form note.
        
        Args:
            key: Note title/key.
            value: Note body content.
            
        Returns:
            Confirmation message.
        """
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO notes (key, content, updated_at) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET 
                    content = excluded.content,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))
        
        get_cache_manager().invalidate('memory')
        return "Saved note '%s'." % key
    
    @monitor("sqlite.recall_note")
    def recall_note(self, key: Optional[str] = None) -> str:
        """Recall a saved note.
        
        Args:
            key: Note key to recall, or None to list all notes.
            
        Returns:
            Note content or JSON of all notes.
        """
        conn = self._get_conn()
        
        if not key:
            rows = conn.execute("SELECT key, content FROM notes ORDER BY key").fetchall()
            if not rows:
                return "No notes stored yet."
            notes = {row['key']: row['content'] for row in rows}
            return json.dumps(notes, indent=2)
        
        row = conn.execute("SELECT content FROM notes WHERE key = ?", (key,)).fetchone()
        if row:
            return row['content']
        return "No note found for '%s'." % key
    
    # ==================== REMINDERS ====================
    
    @monitor("sqlite.add_reminder")
    def add_reminder(self, text: str, minutes_from_now: int = 0) -> str:
        """Set a reminder for the user.
        
        Args:
            text: What to remind about.
            minutes_from_now: Minutes from now to fire (0 = due immediately).
            
        Returns:
            Confirmation message with due time.
        """
        due = datetime.datetime.now() + datetime.timedelta(minutes=minutes_from_now)
        
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO reminders (text, due, created)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (text, due.isoformat()))
        
        get_cache_manager().invalidate('memory')
        
        if minutes_from_now:
            when = due.strftime("%Y-%m-%d %H:%M")
            return "Reminder set for %s: %s" % (when, text)
        return "Reminder set (due now): %s" % text
    
    @monitor("sqlite.list_reminders")
    def list_reminders(self) -> str:
        """List all pending reminders.
        
        Returns:
            Formatted list of pending reminders.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT due, text FROM reminders WHERE done = 0 ORDER BY due"
        ).fetchall()
        
        if not rows:
            return "No pending reminders, sir."
        return "\n".join("[%s] %s" % (row['due'], row['text']) for row in rows)
    
    def due_reminders(self, quiet_minutes: int = 0) -> List[Dict[str, Any]]:
        """Get due reminders - not cached as time-sensitive.
        
        Args:
            quiet_minutes: Suppress reminders notified within this many minutes.
            
        Returns:
            List of due reminder dictionaries.
        """
        conn = self._get_conn()
        now = datetime.datetime.now().isoformat()
        
        query = """
            SELECT id, text, due, created, last_notified 
            FROM reminders 
            WHERE done = 0 AND due <= ?
        """
        rows = conn.execute(query, (now,)).fetchall()
        
        out = []
        for row in rows:
            r = dict(row)
            if quiet_minutes and r.get('last_notified'):
                try:
                    ln = datetime.datetime.fromisoformat(r['last_notified'])
                    if (datetime.datetime.now() - ln).total_seconds() < quiet_minutes * 60:
                        continue
                except Exception:
                    pass
            out.append(r)
        return out
    
    def mark_notified(self, text: str) -> None:
        """Mark a reminder as notified.
        
        Args:
            text: Text to match for marking as notified.
        """
        now = datetime.datetime.now().isoformat()
        with self._transaction() as conn:
            conn.execute("""
                UPDATE reminders 
                SET last_notified = ? 
                WHERE done = 0 AND LOWER(text) LIKE LOWER(?)
            """, (now, f"%{text}%"))
    
    @monitor("sqlite.complete_reminder")
    def complete_reminder(self, text: str) -> str:
        """Mark a reminder as done by matching text.
        
        Args:
            text: Text to match for completion.
            
        Returns:
            Confirmation message.
        """
        with self._transaction() as conn:
            cursor = conn.execute("""
                UPDATE reminders 
                SET done = 1 
                WHERE done = 0 AND LOWER(text) LIKE LOWER(?)
            """, (f"%{text}%",))
            
            if cursor.rowcount > 0:
                get_cache_manager().invalidate('memory')
                return "Marked reminder done: %s" % text
        return "No matching reminder found."
    
    # ==================== SEARCH ====================
    
    def search_facts(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        """Full-text search facts.
        
        Args:
            query: Search query.
            limit: Maximum results.
            
        Returns:
            List of matching facts.
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT f.key, f.value 
            FROM facts f
            JOIN facts_fts fts ON f.rowid = fts.rowid
            WHERE facts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        
        return [{'key': row['key'], 'value': row['value']} for row in rows]
    
    def search_notes(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        """Full-text search notes.
        
        Args:
            query: Search query.
            limit: Maximum results.
            
        Returns:
            List of matching notes.
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT n.key, n.content 
            FROM notes n
            JOIN notes_fts nfts ON n.rowid = nfts.rowid
            WHERE notes_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        
        return [{'key': row['key'], 'content': row['content']} for row in rows]
    
    # ==================== MAINTENANCE ====================
    
    def get_stats(self) -> Dict[str, int]:
        """Get memory statistics.
        
        Returns:
            Dictionary with counts of facts, notes, and reminders.
        """
        conn = self._get_conn()
        facts = conn.execute("SELECT COUNT(*) as cnt FROM facts").fetchone()['cnt']
        notes = conn.execute("SELECT COUNT(*) as cnt FROM notes").fetchone()['cnt']
        reminders = conn.execute("SELECT COUNT(*) as cnt FROM reminders WHERE done = 0").fetchone()['cnt']
        
        return {
            'facts': facts,
            'notes': notes,
            'pending_reminders': reminders
        }
    
    def clear_all(self) -> str:
        """Clear all memory data.
        
        Returns:
            Confirmation message.
        """
        with self._transaction() as conn:
            conn.execute("DELETE FROM facts")
            conn.execute("DELETE FROM notes")
            conn.execute("DELETE FROM reminders")
        
        get_cache_manager().invalidate('memory')
        return "All memory cleared."
    
    def migrate_from_json(self, json_path: Optional[str] = None) -> str:
        """Migrate data from JSON store to SQLite.
        
        Args:
            json_path: Path to store.json. If None, uses default path.
            
        Returns:
            Migration summary.
        """
        if json_path is None:
            json_path = os.path.join(DATA_DIR, "store.json")
        
        if not os.path.exists(json_path):
            return "No JSON file found to migrate."
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            return "Failed to read JSON file: %s" % e
        
        migrated = {'facts': 0, 'notes': 0, 'reminders': 0}
        
        # Migrate facts
        for key, value in data.get('facts', {}).items():
            self.remember_fact(key, str(value))
            migrated['facts'] += 1
        
        # Migrate notes
        for key, value in data.get('notes', {}).items():
            self.save_note(key, str(value))
            migrated['notes'] += 1
        
        # Migrate reminders
        for reminder in data.get('reminders', []):
            try:
                due = datetime.datetime.fromisoformat(reminder['due'])
                now = datetime.datetime.now()
                minutes_from_now = max(0, int((due - now).total_seconds() / 60))
                self.add_reminder(reminder['text'], minutes_from_now)
                migrated['reminders'] += 1
            except Exception:
                continue
        
        # Backup old JSON file
        backup_path = json_path + ".backup"
        if os.path.exists(json_path):
            os.replace(json_path, backup_path)
        
        return "Migrated %d facts, %d notes, %d reminders from JSON." % (
            migrated['facts'], migrated['notes'], migrated['reminders']
        )
    
    def shutdown(self) -> None:
        """Close database connections."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Global singleton instance
_store: Optional[MemoryStore] = None
_store_lock: threading.Lock = threading.Lock()


def _get_store() -> MemoryStore:
    """Get the global memory store instance."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = MemoryStore()
    return _store


# ==================== PUBLIC API (Drop-in replacement) ====================

def remember_fact(key: str, value: str) -> str:
    """Store a persistent fact about the user."""
    return _get_store().remember_fact(key, value)


def recall_fact(key: Optional[str] = None) -> str:
    """Recall a stored fact about the user."""
    return _get_store().recall_fact(key)


def save_note(key: str, value: str) -> str:
    """Save a free-form note."""
    return _get_store().save_note(key, value)


def recall_note(key: Optional[str] = None) -> str:
    """Recall a saved note."""
    return _get_store().recall_note(key)


def add_reminder(text: str, minutes_from_now: int = 0) -> str:
    """Set a reminder for the user."""
    return _get_store().add_reminder(text, minutes_from_now)


def list_reminders() -> str:
    """List all pending reminders."""
    return _get_store().list_reminders()


def due_reminders(quiet_minutes: int = 0) -> List[Dict[str, Any]]:
    """Get due reminders."""
    return _get_store().due_reminders(quiet_minutes)


def mark_notified(text: str) -> None:
    """Mark a reminder as notified."""
    _get_store().mark_notified(text)


def complete_reminder(text: str) -> str:
    """Mark a reminder as done."""
    return _get_store().complete_reminder(text)


def force_save() -> None:
    """No-op for compatibility - SQLite commits immediately."""
    pass


def shutdown() -> None:
    """Shutdown memory module."""
    if _store:
        _store.shutdown()


# Search functions (new additions)
def search_facts(query: str, limit: int = 10) -> List[Dict[str, str]]:
    """Full-text search facts."""
    return _get_store().search_facts(query, limit)


def search_notes(query: str, limit: int = 10) -> List[Dict[str, str]]:
    """Full-text search notes."""
    return _get_store().search_notes(query, limit)


def get_stats() -> Dict[str, int]:
    """Get memory statistics."""
    return _get_store().get_stats()


def clear_all() -> str:
    """Clear all memory data."""
    return _get_store().clear_all()


def migrate_from_json(json_path: Optional[str] = None) -> str:
    """Migrate data from JSON store to SQLite."""
    return _get_store().migrate_from_json(json_path)
