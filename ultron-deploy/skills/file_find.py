NAME = "file_find"
DESCRIPTION = "Find files by name pattern under a directory."
TRIGGERS = ["find file", "search files", "locate file", "where is my file"]

import os


def run(pattern="*.py", root=".", max_results=20, **kwargs):
    matches = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if pattern.lower() in name.lower():
                matches.append(os.path.join(dirpath, name))
                if len(matches) >= max_results:
                    return "Found (showing first %d):\n%s" % (max_results, "\n".join(matches))
    if not matches:
        return "No files matching '%s' under %s." % (pattern, root)
    return "Found:\n" + "\n".join(matches)
