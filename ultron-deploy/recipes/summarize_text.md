---
name: summarize_text
description: Summarize long text into concise bullet points.
triggers: summarize, tldr, make it short, condense
---

# Summarize Text

When the user gives you text to summarize:

1. Read the full text and identify the 3-5 most important points.
2. Rewrite them as concise bullet points in the user's language.
3. Preserve the original tone and key facts; drop filler and repetition.
4. If the text is already short, return it with a one-line note instead of bullet points.

Example:
Input:  "We shipped the new billing system. It had some bugs on launch day but support handled 200 tickets. Revenue is up 12%."
Output: "- New billing system shipped.
- Launch-day bugs handled by support (200 tickets).
- Revenue up 12%."
