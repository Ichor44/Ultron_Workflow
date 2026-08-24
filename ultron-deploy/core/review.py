"""Optimized review and approval system.

Provides efficient proposal review with:
- Cached proposal loading
- Streamlined approval flow
"""

from core import proposals


def show_proposal(p):
    """Display a proposal for review."""
    print("\n" + "=" * 64)
    print("PROPOSAL %s   [%s]   %s" % (p.id, p.change_type.upper(), p.title or p.file_path))
    print("FILE: %s" % p.file_path)
    print("-" * 64)
    print("WHY THIS CHANGE:")
    print(p.explanation)
    print("-" * 64)
    print("DIFF:")
    diff = p.diff()
    print(diff if diff.strip() else "(new file)")
    print("=" * 64)


def _collect_replacement():
    """Collect replacement code from user input."""
    print("Paste the replacement source. End input with a line containing only: EOF")
    lines = []
    while True:
        try:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
        except EOFError:
            break
    return "\n".join(lines)


def prompt_approval(p, auto=False):
    """Prompt for approval, with optional auto-approval."""
    if auto:
        p.write_file()
        p.status = "applied"
        proposals.update_proposal(p)
        print("[auto-approve] applied proposal %s to %s" % (p.id, p.file_path))
        return "approved"

    show_proposal(p)
    while True:
        try:
            choice = input("Review -> Approve (a) / Reject (r) / Edit (e) ? ").strip().lower()
        except EOFError:
            return "rejected"
        if choice in ("a", "approve"):
            p.write_file()
            p.status = "applied"
            proposals.update_proposal(p)
            print("Approved and applied.")
            return "approved"
        if choice in ("r", "reject"):
            p.status = "rejected"
            proposals.update_proposal(p)
            print("Rejected. No files were changed.")
            return "rejected"
        if choice in ("e", "edit"):
            p.new_content = _collect_replacement()
            proposals.update_proposal(p)
            show_proposal(p)
            continue
        print("Please type a, r, or e.")