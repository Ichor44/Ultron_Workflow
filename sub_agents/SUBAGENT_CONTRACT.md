# Sub-Agent Completion Contract (MANDATORY)

> Every sub-agent dispatched via the Task tool MUST follow this contract.
> Orchestrators MUST paste this contract into every dispatch prompt.
> Reason: sub-agents have historically returned `completed` with EMPTY results
> when they exhausted their budget mid-task. "Completed" is not "done" — only
> verified evidence counts.

## 1. Report File (crash-proof record)

- At task **START**: create `C:\Users\Zaki\AppData\Local\Temp\opencode\reports\<agent>-<yyyymmdd-hhmmss>.md`
  whose first line is `STARTED: <one-line summary of the task>`.
- **DURING** work: append one bullet per completed change (`- <file>: <change>`).
- At task **END**: append `## Final Report` containing your full report.

Why: this file survives even if your session dies, times out, or returns an
empty message. The orchestrator (and Hera) will read this file to audit your work.

## 2. Final Message (never silent)

- ALWAYS end your session with a non-empty final TEXT report containing:
  1. What changed (file-by-file)
  2. Decisions taken on ambiguous items
  3. Verification result (see §3)
- If you could NOT complete the task, your final message MUST say so explicitly,
  stating: what failed, what you changed anyway (if anything), and what remains.
  An empty, partial-without-explanation, or missing report is a CONTRACT VIOLATION.

## 3. Verification Before Claiming Completion

- Run whatever verification the dispatch prompt specifies (typecheck, lint,
  tests) OR, at minimum, confirm your claimed file edits exist:
  `(Get-Item <file>).LastWriteTime`
- Include a `Verification:` line with the exact command and outcome.
- Separate PRE-EXISTING issues from issues YOU introduced.

## 4. Scope Discipline (prevents context exhaustion)

- Prefer ONE file per task; never exceed two.
- Do NOT re-read large files you already understand; do NOT run full builds
  unless explicitly instructed.
- If you realize the task is bigger than scoped: STOP, finish the smallest
  coherent slice, and report the remainder as follow-up work in your final
  message. Do not silently abandon the task.
