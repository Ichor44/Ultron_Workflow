NAME = "obsidian_memory"
DESCRIPTION = "Read, write, search, and manage notes in the Ultron_brain Obsidian vault for persistent memory."
TRIGGERS = ["remember", "recall", "note", "vault", "obsidian", "brain", "memory", "search notes", "save to vault"]

import os
import glob
import re
from datetime import datetime

VAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Ultron_brain") if "__file__" in dir() else os.path.join(os.getcwd(), "Ultron_brain")


def _vault_path():
    return os.environ.get("AGENT_VAULT_PATH", VAULT_PATH)


def _ensure_vault():
    path = _vault_path()
    os.makedirs(path, exist_ok=True)
    return path


def _list_notes():
    vault = _vault_path()
    notes = []
    for f in glob.glob(os.path.join(vault, "**", "*.md"), recursive=True):
        rel = os.path.relpath(f, vault)
        notes.append(rel)
    return notes


def _read_note(name):
    vault = _vault_path()
    if not name.endswith(".md"):
        name += ".md"
    path = os.path.join(vault, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _write_note(name, content):
    vault = _ensure_vault()
    if not name.endswith(".md"):
        name += ".md"
    path = os.path.join(vault, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _search_notes(query):
    vault = _vault_path()
    results = []
    query_lower = query.lower()
    for f in glob.glob(os.path.join(vault, "**", "*.md"), recursive=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = fh.read()
            if query_lower in content.lower():
                rel = os.path.relpath(f, vault)
                lines = content.split("\n")
                snippet = ""
                for line in lines:
                    if query_lower in line.lower():
                        snippet = line.strip()[:200]
                        break
                results.append({"file": rel, "snippet": snippet})
        except Exception:
            continue
    return results


def run(action="list", name="", content="", query="", **kwargs):
    action = action.lower()

    if action == "list":
        notes = _list_notes()
        if not notes:
            return "Vault is empty. Start by saving a note with: obsidian_memory action=write name='My Note' content='...'"
        return "Notes in vault:\n" + "\n".join("- %s" % n for n in notes)

    elif action == "read":
        if not name:
            return "Provide a note name to read."
        text = _read_note(name)
        if text is None:
            return "Note '%s' not found." % name
        return "--- %s ---\n%s" % (name, text)

    elif action == "write":
        if not name:
            return "Provide a note name."
        if not content:
            return "Provide content to save."
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        frontmatter = "---\ntitle: %s\ndate: %s\ntags:\n  - agent-memory\n---\n\n" % (name, now)
        path = _write_note(name, frontmatter + content)
        return "Saved to vault: %s" % os.path.relpath(path, _vault_path())

    elif action == "search":
        if not query:
            return "Provide a query to search."
        results = _search_notes(query)
        if not results:
            return "No notes matching '%s'." % query
        out = "Found %d note(s):\n" % len(results)
        for r in results[:10]:
            out += "- %s: %s\n" % (r["file"], r["snippet"][:100])
        return out

    elif action == "append":
        if not name:
            return "Provide a note name to append to."
        if not content:
            return "Provide content to append."
        existing = _read_note(name) or ""
        new_content = existing + "\n\n" + content
        _write_note(name, new_content)
        return "Appended to '%s'." % name

    elif action == "daily":
        today = datetime.now().strftime("%Y-%m-%d")
        name = "Daily/%s" % today
        existing = _read_note(name)
        if existing:
            return "Today's note exists:\n%s" % existing
        now = datetime.now().strftime("%H:%M")
        content = "---\ntitle: %s\ndate: %s\ntags:\n  - daily\n---\n\n## Log\n\n**%s** - Session started\n" % (today, today, now)
        _write_note(name, content)
        return "Created daily note: %s" % name

    elif action == "remember":
        if not content:
            return "Provide something to remember."
        now = datetime.now().strftime("%Y-%m-%d")
        name = "Memory/%s" % datetime.now().strftime("%Y%m%d-%H%M%S")
        content_full = "---\ntitle: Memory\ndate: %s\ntags:\n  - memory\n  - fact\n---\n\n%s" % (now, content)
        _write_note(name, content_full)
        return "Remembered: %s" % content[:80]

    elif action == "recall":
        if not query:
            query = ""
        results = _search_notes(query) if query else []
        if not results:
            memory_notes = []
            for f in glob.glob(os.path.join(_vault_path(), "Memory", "*.md")):
                rel = os.path.relpath(f, _vault_path())
                memory_notes.append(rel)
            if memory_notes:
                return "Memory notes:\n" + "\n".join("- %s" % n for n in memory_notes[-10:])
            return "No memories stored yet."
        out = "Memories matching '%s':\n" % query
        for r in results[:5]:
            out += "- %s: %s\n" % (r["file"], r["snippet"][:120])
        return out

    elif action == "index":
        notes = _list_notes()
        vault = _vault_path()
        index = "# Ultron Brain Index\n\n"
        categories = {}
        for n in notes:
            cat = os.path.dirname(n) or "Root"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(n)
        for cat in sorted(categories.keys()):
            index += "## %s\n\n" % cat
            for n in sorted(categories[cat]):
                index += "- [[%s]]\n" % os.path.splitext(os.path.basename(n))[0]
            index += "\n"
        _write_note("index", index)
        return "Index updated with %d notes." % len(notes)

    elif action == "stats":
        notes = _list_notes()
        vault = _vault_path()
        total_size = 0
        for f in glob.glob(os.path.join(vault, "**", "*.md"), recursive=True):
            total_size += os.path.getsize(f)
        return "Vault stats: %d notes, %.1f KB total" % (len(notes), total_size / 1024)

    else:
        return "Unknown action. Use: list, read, write, search, append, daily, remember, recall, index, stats"
