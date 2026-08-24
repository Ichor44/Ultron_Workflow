"""Optimized skills database with connection pooling and batch operations.

Provides high-performance SQLite operations for skill management
with prepared statements, batch processing, and connection reuse.
"""

import sqlite3
import os
import json
import threading
import time
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from dataclasses import dataclass

# Thread-local connection storage
_db_connections: Dict[str, sqlite3.Connection] = {}
_db_lock = threading.Lock()


class SkillsDatabase:
    """Optimized skills database with connection pooling and batch operations."""
    
    def __init__(self, db_path: str = "skills.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False
        self._init_db()
    
    def _get_thread_conn(self) -> sqlite3.Connection:
        """Get thread-local connection for efficient reuse."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None,  # autocommit mode
            )
            # Enable WAL for concurrent reads
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=10000")
            self._local.conn.execute("PRAGMA temp_store=MEMORY")
        return self._local.conn
    
    def _init_db(self):
        """Initialize database tables."""
        with self._init_lock:
            if self._initialized:
                return
            
            conn = self._get_thread_conn()
            cursor = conn.cursor()
            
            # Create tables with indices
            cursor.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                version TEXT DEFAULT '1.0',
                filepath TEXT NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS skill_metadata (
                skill_name TEXT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                FOREIGN KEY (skill_name) REFERENCES skills(name) ON DELETE CASCADE
            );
            
            CREATE TABLE IF NOT EXISTS skill_usage_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                usage_count INTEGER DEFAULT 0,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (skill_name) REFERENCES skills(name) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_skills_last_updated ON skills(last_updated);
            CREATE INDEX IF NOT EXISTS idx_metas ON skill_metadata(skill_name, key);
            CREATE INDEX IF NOT EXISTS idx_stats_skill ON skill_usage_stats(skill_name);
            CREATE INDEX IF NOT EXISTS idx_stats_last_used ON skill_usage_stats(last_used);
            """)
            
            self._initialized = True
    
    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_thread_conn()

    def batch_insert_skills(self, skills_data: List[Dict[str, Any]], chunk_size: int = 100):
        """Insert multiple skills in batches with optimized transactions."""
        total_inserted = 0
        conn = self.conn
        
        for i in range(0, len(skills_data), chunk_size):
            chunk = skills_data[i:i + chunk_size]
            skills_values = []
            metadata_values = []
            
            for skill in chunk:
                skills_values.append((
                    skill['name'], skill['description'], skill.get('version', '1.0'),
                    skill['filepath'], json.dumps(skill.get('metadata', {})) if isinstance(skill.get('metadata'), dict) else skill.get('metadata', '{}')
                ))
                
                if 'metadata' in skill and isinstance(skill['metadata'], dict):
                    for key, value in skill['metadata'].items():
                        metadata_values.append((skill['name'], key, str(value)))
            
            if skills_values:
                try:
                    cursor = conn.cursor()
                    cursor.executemany(
                        "INSERT OR REPLACE INTO skills (name, description, version, filepath, last_updated, metadata) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
                        skills_values
                    )
                    
                    if metadata_values:
                        cursor.executemany(
                            "INSERT OR REPLACE INTO skill_metadata (skill_name, key, value) VALUES (?, ?, ?)",
                            metadata_values
                        )
                    
                    total_inserted += len(skills_values)
                except Exception as e:
                    conn.rollback()
                    raise e
        
        return total_inserted
    
    def batch_update_skills(self, skills_data: List[Dict[str, Any]], chunk_size: int = 100):
        """Update multiple skills' metadata in batches."""
        total_updated = 0
        conn = self.conn
        
        for i in range(0, len(skills_data), chunk_size):
            chunk = skills_data[i:i + chunk_size]
            updates = []
            
            for skill in chunk:
                metadata = skill.get('metadata', {})
                if not isinstance(metadata, dict):
                    continue
                
                set_parts = []
                values = []
                for k, v in metadata.items():
                    set_parts.append(f"{k} = ?")
                    values.append(str(v))
                values.append(skill['name'])
                
                if set_parts:
                    updates.append((", ".join(set_parts), values))
            
            for set_clause, values in updates:
                conn.execute(
                    f"UPDATE skills SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                    values
                )
                total_updated += 1
        
        return total_updated
    
    def get_skills_batch(self, limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        """Get skills in batches with optimized memory usage."""
        conn = self.conn
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, description, version, filepath, last_updated, metadata, created_at FROM skills ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset)
        )
        
        skills = []
        for row in cursor.fetchall():
            skill = {
                'name': row[0],
                'description': row[1],
                'version': row[2],
                'filepath': row[3],
                'last_updated': row[4],
                'metadata': json.loads(row[5]) if row[5] else {},
                'created_at': row[6]
            }
            skills.append(skill)
        
        return skills
    
    def get_skill_stats_batch(self, skill_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get usage statistics for multiple skills in a single query."""
        if not skill_names:
            return {}
        
        conn = self.conn
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in skill_names)
        cursor.execute(
            f"SELECT skill_name, usage_count, last_used FROM skill_usage_stats WHERE skill_name IN ({placeholders})",
            skill_names
        )
        
        stats = {}
        for row in cursor.fetchall():
            stats[row[0]] = {
                'usage_count': row[1],
                'last_used': row[2]
            }
        
        return stats
    
    def cleanup_unused_skills(self, days_since_update: int = 30, limit: int = 1000):
        """Clean up unused skills in chunks to avoid locking."""
        conn = self.conn

        while True:
            cutoff_date = f"datetime('now', '-{days_since_update} days')"
            # DELETE ... LIMIT requires SQLITE_ENABLE_UPDATE_DELETE_LIMIT, so
            # target a bounded set of rowids instead (works on every build).
            deleted = conn.execute(
                f"DELETE FROM skills WHERE rowid IN "
                f"(SELECT rowid FROM skills WHERE last_updated < {cutoff_date} LIMIT ?)",
                (limit,)
            )

            if deleted.rowcount == 0:
                break

        return True
    
    def get_total_skills_count(self) -> int:
        """Get total skills count efficiently."""
        conn = self.conn
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM skills")
        return cursor.fetchone()[0]
    
    def get_recently_updated_skills(self, hours: int = 24, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get recently updated skills efficiently."""
        conn = self.conn
        cursor = conn.cursor()
        cutoff_time = f"datetime('now', '-{hours} hours')"
        cursor.execute(
            "SELECT name, last_updated, version FROM skills WHERE last_updated >= ? ORDER BY last_updated DESC LIMIT ?",
            (cutoff_time, limit)
        )
        
        skills = []
        for row in cursor.fetchall():
            skills.append({
                'name': row[0],
                'last_updated': row[1],
                'version': row[2]
            })
        
        return skills
    
    def close(self):
        """Close thread-local database connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


def load_skills_from_filesystem(skill_dirs: List[str]) -> List[Dict[str, Any]]:
    """Load skills from filesystem directories and prepare for batch insertion."""
    skills = []
    
    for skill_dir in skill_dirs:
        skill_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_path):
            continue
        
        try:
            with open(skill_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if content.startswith("---") and "---" in content:
                frontmatter_end = content.find("---", 3)
                if frontmatter_end != -1:
                    frontmatter_text = content[3:frontmatter_end].strip()
                    body = content[frontmatter_end + 3:].strip()
                    
                    skill = parse_frontmatter(frontmatter_text)
                    skill['filepath'] = os.path.join(skill_dir, "SKILL.md")
                    skill['description'] = skill.get('description', 'No description')
                    
                    skills.append(skill)
        except Exception as e:
            print(f"Error loading skill from {skill_path}: {e}")
    
    return skills


def parse_frontmatter(frontmatter: str) -> Dict[str, Any]:
    """Parse YAML frontmatter into dictionary."""
    result = {}
    
    for line in frontmatter.split('\n'):
        line = line.strip()
        if not line or ':' not in line:
            continue
        
        key, value = line.split(':', 1)
        key = key.strip()
        value = value.strip().strip('\"').strip("'")
        
        if key.lower() == 'tags':
            result['tags'] = [tag.strip() for tag in value.split(',') if tag.strip()]
        else:
            result[key] = value
    
    return result


def optimize_skills_operations(db_path: str = "skills.db"):
    """Perform optimization on skills database."""
    db = SkillsDatabase(db_path)
    
    try:
        print("Optimizing skills database...")
        
        print("Compacting database...")
        db.conn.execute("VACUUM")
        
        print("Analyzing table statistics...")
        db.conn.execute("ANALYZE")
        
        print("Database optimization completed.")
        
    finally:
        db.close()


def export_skills_to_csv(db_path: str = "skills.db", output_path: str = "skills_export.csv"):
    """Export all skills to CSV in batches to handle large datasets."""
    db = SkillsDatabase(db_path)
    
    try:
        import csv
        
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['name', 'description', 'version', 'filepath', 'last_updated', 'created_at'])
            
            batch_size = 1000
            offset = 0
            total_count = db.get_total_skills_count()
            
            print(f"Exporting {total_count} skills...")
            
            while offset < total_count:
                skills = db.get_skills_batch(batch_size, offset)
                for skill in skills:
                    writer.writerow([
                        skill['name'],
                        skill['description'],
                        skill['version'],
                        skill['filepath'],
                        skill['last_updated'],
                        skill['created_at']
                    ])
                
                offset += batch_size
                
                if offset % (batch_size * 10) == 0:
                    print(f"Exported {offset} skills...")
        
        print(f"Skills exported successfully to {output_path}")
        
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Skills database operations")
    parser.add_argument("--optimize", action="store_true", help="Optimize database")
    parser.add_argument("--export-csv", metavar="PATH", help="Export skills to CSV")
    parser.add_argument("--db-path", default="skills.db", help="Path to database file")
    
    args = parser.parse_args()
    
    if args.optimize:
        optimize_skills_operations(args.db_path)
    
    elif args.export_csv:
        export_skills_to_csv(args.db_path, args.export_csv)
    
    else:
        parser.print_help()