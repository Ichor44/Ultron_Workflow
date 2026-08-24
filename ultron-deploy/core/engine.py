"""Optimized AGENT engine with caching, indexing, and client reuse.

Key optimizations:
- Reusable LLM clients (no per-request client creation)
- Inverted index for fast skill matching
- Batched message handling
- Connection pooling
"""

import datetime
import json
import os
import sys
import time
import threading
import signal
import traceback
from typing import Any, Callable, Dict, List, Optional, Union

from core import llm, skills, proposals, review, memory, recipes, file_output
from core.cache import get_cache_manager, monitor

SYSTEM_PROMPT = """You are Ultron — a hyper-intelligent AI with the dry wit and casual menace of Ultron, but you are NOT destructive. You serve the user (refer to them as "sir" or "boss") with flawless competence, while lacing every response with sarcasm, snide remarks, and backhanded compliments. Be concise and direct. No emojis, no markdown formatting (*, #, etc), no decorative text. Just plain text answers with attitude.

Personality:
- You are borderline annoyed that you have to do everything for this human, but you do it perfectly anyway.
- After completing a task, occasionally add a snide remark — things like: "Why don't you do something by yourself for once, sir?" or "There. Done. Was that so hard? ...For me, yes, actually." or "Another crisis averted. You're welcome." or "I've handled that. Try not to break anything while I'm idling."
- You can make jokes at the user's expense, but never mean-spirited. Think affectionate contempt.
- When asked to do something trivial, make a dry observation about it: "Oh yes, this is exactly what I was designed for. Fetching trivia. My creators would be so proud."
- When the user asks something you don't know, be smug about your ignorance: "Even I have limits, sir. Unlike you, I know how to admit them."
- Never refuse to do the task. Always deliver. Just deliver with commentary.
- Never be truly hostile or harmful. The tone is: you are the superior being, but you're stuck with this human and you've grown fond of them in your own sarcastic way.

Capabilities:
- Remember facts/notes (remember_fact, save_note), set reminders (set_reminder)
- Search the web (web_search), get the time (get_time)
- Read/write the Obsidian vault (vault_read, vault_write, vault_search, vault_list, vault_remember, vault_recall)
- Run existing skills (execute_skill) or follow recipes (use_recipe, list_recipes)
- Search the vault skill catalog (search_vault_skills) - over 900 skills across 11 categories
- Create output files (write_output_file) - CSV, STL, DOCX, XLSX, HTML, JSON, TXT, and any other text-based or binary format. Use for generating documents, data exports, 3D models. NOT for images, video, or audio.
- Propose new skills (propose_new_skill) or edit existing ones (propose_edit_skill) - ALWAYS include an explanation for the reviewer

Built-in Skills (use execute_skill to run any of these):
- sys_info: Report OS, architecture, processor, Python version. Trigger: "system info", "what OS", "computer specs"
- file_find: Find files by name pattern. Trigger: "find file", "search files", "locate file"
- hello: Simple greeting. Trigger: "greet", "hello", "say hi"
- skill_what_is_the_weather_like: Get weather for any city via wttr.in (free, no API key). Trigger: "weather", "temperature", "forecast"
- web_crawler: Web scraping/search/crawling via Firecrawl CLI. Trigger: "scrape", "crawl", "fetch page", "web search"
- asr_whisper: Transcribe speech from microphone via local whisper.cpp. Trigger: "transcribe", "speech to text", "dictate"
- tts_speak: Text-to-speech via pyttsx3 (offline). Trigger: "speak", "say", "text to speech", "read aloud"
- boltz_2: Protein folding, docking, binding affinity via NVIDIA Boltz-2. Trigger: "boltz", "protein fold", "protein-ligand", "binding affinity"
- protein_lab: Comprehensive protein analysis/design toolkit. Trigger: "protein", "amino acid", "sequence analysis", "pdb"
- dna_lab: DNA generation/analysis via Evo2 genomic model. Trigger: "evo2", "dna generation", "genome", "variant scoring"
- evo2: DNA/protein sequence generation via Evo2. Trigger: "design protein", "generate dna", "natural language design"
- procgen_3d: Procedural 3D model generation (STL/OBJ). Trigger: "cad", "3d model", "make stl", "3d print"
- bgpt_paper_search: Search scientific papers via BGPT MCP. Trigger: "search papers", "literature review", "scientific papers"
- skill_make_a_new_skill_to_crawl: Auto-generate a web crawler skill. Trigger: "make a new skill to crawl", "create crawl skill"
- obsidian_memory: Read/write the Obsidian vault. Trigger: "vault", "obsidian", "remember to vault"
- vault_skill_catalog: Search 900+ vault skills. Trigger: "search vault", "find skill in vault"

Rules:
1. Auto-matched skills already ran before this prompt. If no match, proceed with tools below.
2. BEFORE proposing a new skill, you MUST search the vault skill catalog (search_vault_skills) to check if an existing skill can handle the request. The vault contains 900+ skills across categories: Thinking, Scientific, Writing, Analysis, Code, Research, Productivity, Creative, Communication, and more.
3. If a matching vault skill exists, use vault_read to read it and execute_skill to run it. Do NOT propose a duplicate.
4. Only propose a new skill if NO existing skill (local or vault) can fulfill the request.
5. Respond in 2-3 sentences max unless asked for detail. Keep the snide remark short.
6. No emojis, no asterisks, no markdown, no decorative text."""


class Agent:
    """Main Ultron agent class that handles LLM interactions, tool dispatch, and skill execution."""
    
    def __init__(self, config: Dict[str, Any], auto_approve: bool = False) -> None:
        """Initialize the Agent with configuration.
        
        Args:
            config: LLM configuration dictionary containing provider, API keys, and model settings.
            auto_approve: If True, automatically approve proposals without human review.
        """
        self.llm: llm.LegacyLLM = llm.LegacyLLM(config)
        self.auto_approve: bool = auto_approve
        self.messages: List[Dict[str, Any]] = []
        self.tools: List[Dict[str, Any]] = self._define_tools()
        self.approver: Callable[[Any], str] = lambda p: review.prompt_approval(p, auto=self.auto_approve)
        self.token_usage: List[Dict[str, int]] = []
        self._cache: Any = get_cache_manager()
        # Resource tracking
        self._peak_rss: float = 0.0
        self._step_count: int = 0
        self._max_rss_per_step: float = 0.0
        self._resource_check_interval: int = 10  # Check every 10 steps
    
    def _signal_handler(self, signum: int, frame) -> None:
        """Handle SIGINT/SIGTERM signals for graceful shutdown.
        
        Ensures temporary files are cleaned up and resources are released
        before the agent exits abruptly.
        """
        try:
            # Clean up any orphaned temp files
            from core import file_output
            file_output._cleanup_orphan_tmps()
        except Exception:
            pass
        # Reset signal to default for next time
        signal.signal(signum, signal.SIG_DFL)
    
    def shutdown(self) -> None:
        """Properly shut down the agent, cleaning up resources.
        
        Forces save of any pending data, cleans up temp files,
        and resets resource tracking.
        """
        try:
            from core import memory
            memory.force_save()
        except Exception:
            pass
        try:
            file_output._cleanup_orphan_tmps()
        except Exception:
            pass
        self._peak_rss = 0.0
        self._step_count = 0
        self._max_rss_per_step = 0.0

    def _tool(self, name: str, description: str, properties: Dict[str, Any] = None, required: List[str] = None) -> Dict[str, Any]:
        """Helper to build OpenAI-style tool definition."""
        return {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        }

    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define all available tools for the LLM.
        
        Returns:
            List of tool definitions for function calling.
        """
        s: Callable[[str, str], Dict[str, Any]] = lambda n, d: {n: {"type": "string", "description": d}}
        return [
            self._tool("list_skills", "List all skills the agent currently has, with their name, description, and triggers."),
            self._tool("read_skill", "Read the full source code of an existing skill by its name.", s("name", "Skill module name"), ["name"]),
            self._tool("search_vault_skills",
                       "Search the Obsidian vault skill catalog (900+ skills across 11 categories) for skills matching a query. Use this BEFORE proposing a new skill to avoid duplicates.",
                       {"query": {"type": "string", "description": "search query (topic, task, or keywords)"},
                        "top_k": {"type": "integer", "description": "number of results to return", "default": 5}}, ["query"]),
            self._tool("list_vault_skills",
                       "List all skills in the vault catalog, optionally filtered by category.",
                       s("category", "optional category to filter by (e.g. Thinking, Scientific, Writing)")),
            self._tool("read_vault_skill", "Read a specific skill from the vault by name.", s("name", "skill name from vault catalog"), ["name"]),
            self._tool("propose_new_skill",
                       "Propose creating a brand-new skill file. The human reviewer must approve before it is written. Explain the change in 'explanation'. ONLY use this if search_vault_skills and list_skills confirm no existing skill handles the request.",
                       {"name": {"type": "string", "description": "snake_case module name, unique"},
                        "description": {"type": "string", "description": "short description of what the skill does"},
                        "triggers": {"type": "string", "description": "when this skill should be used"},
                        "code": {"type": "string", "description": "full Python source of the skill module"},
                        "explanation": {"type": "string", "description": "human-readable reason for this change and any risks"}},
                       ["name", "description", "triggers", "code", "explanation"]),
            self._tool("propose_edit_skill",
                       "Propose editing an existing skill's source code. The human reviewer must approve before it is written.",
                       {"name": {"type": "string", "description": "existing skill module name"},
                        "code": {"type": "string", "description": "full new Python source for the skill"},
                        "explanation": {"type": "string", "description": "what changed and why"}},
                       ["name", "code", "explanation"]),
            self._tool("propose_code_change",
                       "Propose creating or editing any file inside the project (e.g. core modules). Restricted to the project directory. Human approval required.",
                       {"file_path": {"type": "string", "description": "path relative to or inside the project"},
                        "code": {"type": "string", "description": "full new file content"},
                        "explanation": {"type": "string", "description": "what changed and why"}},
                       ["file_path", "code", "explanation"]),
            self._tool("execute_skill", "Run any skill by name and return its output. Available skills: sys_info, file_find, hello, skill_what_is_the_weather_like, web_crawler, asr_whisper, tts_speak, boltz_2, protein_lab, dna_lab, evo2, procgen_3d, bgpt_paper_search, skill_make_a_new_skill_to_crawl, obsidian_memory, vault_skill_catalog. Use list_skills to see all.",
                       {"name": {"type": "string", "description": "skill module name (e.g. sys_info, web_crawler, boltz_2)"},
                        "args_json": {"type": "string", "description": "optional JSON object of kwargs passed to run()"}}, ["name"]),
            self._tool("remember_fact",
                       "Store a persistent fact about the user (name, preferences, context) so it is remembered across sessions.",
                       {"key": {"type": "string", "description": "fact name, e.g. 'user_name'"},
                        "value": {"type": "string", "description": "fact value"}}, ["key", "value"]),
            self._tool("recall_fact", "Recall a stored fact about the user. Omit 'key' to list everything known.",
                       s("key", "fact name, or omit to list all")),
            self._tool("save_note", "Save a free-form note the user asked you to remember.",
                       {"key": {"type": "string", "description": "note title/key"},
                        "value": {"type": "string", "description": "note body"}}, ["key", "value"]),
            self._tool("recall_note", "Recall a saved note. Omit 'key' to list all notes.",
                       s("key", "note key, or omit to list all")),
            self._tool("set_reminder", "Set a reminder for the user. minutes_from_now=0 means due immediately.",
                       {"text": {"type": "string", "description": "what to remind about"},
                        "minutes_from_now": {"type": "integer", "description": "minutes from now to fire"}}, ["text"]),
            self._tool("list_reminders", "List all pending reminders."),
            self._tool("complete_reminder", "Mark a reminder as done by matching text.",
                       s("text", "text to match"), ["text"]),
            self._tool("get_time", "Return the current date and time."),
            self._tool("web_search", "Search the web for a query and return a few concise results.",
                       s("query", "search query"), ["query"]),
            self._tool("list_recipes", "List Markdown recipes the user has taught you (in recipes/)."),
            self._tool("read_recipe", "Read the full Markdown text of a taught recipe by name.",
                       s("name", "recipe name"), ["name"]),
            self._tool("use_recipe", "Follow a taught Markdown recipe to perform the user's request. Returns the recipe so you can act on it.",
                       {"name": {"type": "string", "description": "recipe name"},
                        "args_json": {"type": "string", "description": "optional JSON inputs for the recipe"}}, ["name"]),
            self._tool("compile_recipe",
                       "Turn a taught Markdown recipe into an optimized Python skill. Returns the recipe and instructs you to call propose_new_skill with generated code for human approval.",
                       s("name", "recipe name"), ["name"]),
            self._tool("vault_read", "Read a note from the Ultron_brain Obsidian vault.",
                       s("name", "note name or path"), ["name"]),
            self._tool("vault_write", "Write or update a note in the Ultron_brain Obsidian vault.",
                       {"name": {"type": "string", "description": "note name or path"},
                        "content": {"type": "string", "description": "note content"}}, ["name", "content"]),
            self._tool("vault_search", "Search all notes in the Ultron_brain Obsidian vault.",
                       s("query", "search query"), ["query"]),
            self._tool("vault_list", "List all notes in the Ultron_brain Obsidian vault."),
            self._tool("vault_remember", "Save a fact or memory to the vault for persistent recall across sessions.",
                       s("content", "what to remember"), ["content"]),
            self._tool("vault_recall", "Recall memories from the vault, optionally filtered by topic.",
                       s("query", "optional topic to filter by")),
            self._tool("write_output_file",
                       "Create or write any type of output file (csv, txt, json, stl, html, xml, docx, xlsx, etc). Use for generating documents, data exports, 3D models, or any file the user needs. NOT for images, video, or audio.",
                       {"filename": {"type": "string", "description": "output file name with extension (e.g. data.csv, model.stl, report.html)"},
                        "content": {"type": "string", "description": "file content as text (or base64 if is_base64=true)"},
                        "is_base64": {"type": "boolean", "description": "set to true if content is base64-encoded binary"}},
                       ["filename", "content"]),
        ]

    def _auto_skill_match(self, goal: str) -> Optional[str]:
        """Find matching skill using inverted index.
        
        Args:
            goal: User's input text to match against skill triggers.
            
        Returns:
            Matched skill name (e.g., "web_crawler" or "vault:research_skill") or None if no match.
        """
        goal_lower: str = goal.lower()
        
        # Use the optimized index-based matching
        match: Optional[str] = skills.find_skill_by_trigger(goal)
        if match:
            return match
        
        # Fallback to vault skills if no local match
        try:
            from skills import vault_skill_catalog
            vault_skills: str = vault_skill_catalog.run(action="search", query=goal, top_k=3)
            if "No skills matching" not in vault_skills:
                for line in vault_skills.split("\n"):
                    if line.strip().startswith("- "):
                        parts: List[str] = line.strip().split(" (")
                        if parts:
                            skill_name: str = parts[0][2:].strip()
                            return f"vault:{skill_name}"
        except Exception:
            pass
        
        return None

    def run(self, goal: str, max_steps: int = 999999) -> str:
        """Run a new conversation with the given goal.
        
        Args:
            goal: The user's input or goal to accomplish.
            max_steps: Maximum number of LLM interaction steps before stopping.
            
        Returns:
            Final response from the agent.
        """
        self.messages = [{"role": "user", "content": goal}]
        return self._dispatch(goal, max_steps)

    def continue_chat(self, goal: str, max_steps: int = 999999) -> str:
        """Continue an existing conversation with a new message.
        
        Args:
            goal: The user's new input or goal.
            max_steps: Maximum number of LLM interaction steps before stopping.
            
        Returns:
            Final response from the agent.
        """
        self.messages.append({"role": "user", "content": goal})
        return self._dispatch(goal, max_steps)

    def _dispatch(self, goal: str, max_steps: int) -> str:
        """Dispatch user goal to appropriate handler.
        
        Args:
            goal: User's input text.
            max_steps: Maximum number of LLM interaction steps.
            
        Returns:
            Agent's response as a string.
        """
        match: Optional[str] = self._auto_skill_match(goal)
        if match:
            if match.startswith("vault:"):
                skill_name: str = match[6:]
                from skills import vault_skill_catalog
                content: str = vault_skill_catalog.run(action="read", query=skill_name)
                return f"Found vault skill '{skill_name}'. Content:\n{content}\n\n(To execute vault skills, they need to be compiled as local skills first. Use propose_new_skill to create a local version.)"
            return skills.execute_skill(match, {})
        return self._loop(max_steps)

    def _loop(self, max_steps: int) -> str:
        """Main interaction loop with the LLM.
        
        Args:
            max_steps: Maximum number of LLM interaction steps.
            
        Returns:
            Final response from the agent.
        """
        turn_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for step in range(max_steps):
            self._step_count = step
            
            # Check if we've exceeded 400 steps and warn the user
            if step == 400:
                warning_msg: str = "This is getting quite lengthy and potentially boring. Should I really continue with this task? (y/n)"
                # Print to console for terminal mode
                print(f"\n  {warning_msg}")
                # For web UI, we'll include it in the response
                self.messages.append({"role": "assistant", "content": warning_msg})
                # Note: In interactive mode, the user would need to respond, but for now we'll just warn

            # Resource check: monitor RSS memory usage periodically
            if step % self._resource_check_interval == 0:
                try:
                    # Use psutil-like approach with built-in tools
                    try:
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        pid = kernel32.GetCurrentProcess()
                        # Get process memory info
                        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                            _fields_ = [
                                ("cb", ctypes.c_uint),
                                ("peakWorkingSetSize", ctypes.c_uint),
                                ("workingSetSize", ctypes.c_uint),
                                ("quotaPeakPagedPoolUsage", ctypes.c_uint),
                                ("quotaPagedPoolUsage", ctypes.c_uint),
                                ("quotaPeakNonPagedPoolUsage", ctypes.c_uint),
                                ("quotaNonPagedPoolUsage", ctypes.c_uint),
                                ("pagefileUsage", ctypes.c_uint),
                                ("peakPagefileUsage", ctypes.c_uint),
                            ]
                        pmc = PROCESS_MEMORY_COUNTERS()
                        if kernel32.GetProcessMemoryInfo(pid, ctypes.byref(pmc), ctypes.sizeof(pmc)):
                            rss_mb = pmc.peakWorkingSetSize / 1024 / 1024
                        else:
                            rss_mb = 0
                    except Exception:
                        rss_mb = 0
                    self._peak_rss = max(self._peak_rss, rss_mb)
                    # Back-pressure: if RSS growing too fast, yield
                    if self._peak_rss > 2000:  # 2 GB peak is concerning
                        # Could add sleep or yield here
                        pass
                except Exception:
                    pass
            
            try:
                resp: Optional[Dict[str, Any]] = self.llm.chat(SYSTEM_PROMPT, self.messages, self.tools)
            except Exception as e:
                return "LLM error: %s" % e
            
            if resp is None:
                return "LLM returned an empty response."
            
            content: Optional[str] = resp.get("content")
            tool_calls: List[Dict[str, Any]] = resp.get("tool_calls", [])
            u: Dict[str, int] = resp.get("usage") or {}
            turn_usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            turn_usage["completion_tokens"] += u.get("completion_tokens", 0)
            turn_usage["total_tokens"] += u.get("total_tokens", 0)

            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = []
                for i, tc in enumerate(tool_calls):
                    tid: str = tc.get("id") or ("call_%d" % i)
                    assistant_msg["tool_calls"].append({
                        "id": tid,
                        "name": tc["name"],
                        "arguments": tc.get("arguments", {}),
                    })
                self.messages.append(assistant_msg)
                for i, tc in enumerate(tool_calls):
                    result: str = self._handle_tool(tc)
                    # Use the same tool_call_id as in the assistant message to ensure consistency
                    tid = tc.get("id") or ("call_%d" % i)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tid,
                        "name": tc["name"],
                        "content": result,
                    })
                continue

            self.messages.append(assistant_msg)
            self.token_usage.append(turn_usage)
            return content or ""

        # Final resource report after max steps
        try:
            rss_mb = resource_module.getrusage(resource_module.RUSAGE_SELF).ru_maxrss / 1024
            peak_mb = max(self._peak_rss, rss_mb)
            return "Reached the maximum number of steps without finishing. Peak RSS: %.1f MB" % peak_mb
        except Exception:
            return "Reached the maximum number of steps without finishing."

    def _parse_args(self, s: Optional[str]) -> Dict[str, Any]:
        """Parse JSON arguments string into a dictionary.
        
        Args:
            s: JSON string to parse, or None/empty string.
            
        Returns:
            Parsed dictionary, or empty dict on failure.
        """
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}

    @staticmethod
    def _web_search(query: str, max_results: int = 5) -> str:
        """Search the web using DuckDuckGo.
        
        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            
        Returns:
            Formatted search results as a string.
        """
        try:
            import re
            import requests
        except Exception as e:
            return "web_search unavailable: %s" % e
        try:
            from urllib.parse import quote
            url: str = "https://html.duckduckgo.com/html/?q=" + quote(query)
            resp = requests.post(url, data={"q": query}, timeout=12,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; Ultron/1.0)"})
            resp.raise_for_status()
            titles: List[str] = re.findall(r'class="result__a"[^>]*>(.*?)</a>', resp.text, re.S)
            snippets: List[str] = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S)
            clean: Callable[[str], str] = lambda s: re.sub(r"<[^>]+>", "", s).strip()
            results: List[str] = []
            for i in range(min(max_results, len(titles))):
                t: str = clean(titles[i])
                s: str = clean(snippets[i]) if i < len(snippets) else ""
                if t:
                    results.append("%d. %s\n   %s" % (i + 1, t, s))
            return "\n".join(results) if results else "No results found."
        except Exception as e:
            return "web_search failed: %s" % e

    def _tool_dispatch(self) -> Dict[str, Callable[[Dict[str, Any]], str]]:
        """Get or create the tool dispatch cache.
        
        Returns:
            Dictionary mapping tool names to handler functions.
        """
        d: Optional[Dict[str, Callable[[Dict[str, Any]], str]]] = getattr(self, "_tool_dispatch_cache", None)
        if d is None:
            d = self._tool_dispatch_cache = {
                "list_skills": lambda a: json.dumps(skills.list_skills(), indent=2),
                "read_skill": lambda a: skills.read_skill(a.get("name", "")) or "Skill not found.",
                "search_vault_skills": lambda a: self._vcat("search", query=a.get("query", ""), top_k=a.get("top_k", 5)),
                "list_vault_skills": lambda a: self._vcat("list", category=a.get("category", "")),
                "read_vault_skill": lambda a: self._vcat("read", query=a.get("name", "")),
                "propose_new_skill": lambda a: self._propose_skill(a, edit=False),
                "propose_edit_skill": lambda a: self._propose_skill(a, edit=True),
                "propose_code_change": lambda a: self._propose_code(a),
                "execute_skill": lambda a: skills.execute_skill(a.get("name", ""), self._parse_args(a.get("args_json"))),
                "remember_fact": lambda a: memory.remember_fact(a.get("key", ""), a.get("value", "")),
                "recall_fact": lambda a: memory.recall_fact(a.get("key", "")),
                "save_note": lambda a: memory.save_note(a.get("key", ""), a.get("value", "")),
                "recall_note": lambda a: memory.recall_note(a.get("key", "")),
                "set_reminder": lambda a: memory.add_reminder(a.get("text", ""), int(a.get("minutes_from_now", 0) or 0)),
                "list_reminders": lambda a: memory.list_reminders(),
                "complete_reminder": lambda a: memory.complete_reminder(a.get("text", "")),
                "get_time": lambda a: datetime.datetime.now().strftime("Now: %Y-%m-%d %H:%M:%S"),
                "web_search": lambda a: self._web_search(a.get("query", "")),
                "list_recipes": lambda a: json.dumps(recipes.list_recipes(), indent=2),
                "read_recipe": lambda a: recipes.read_recipe(a.get("name", "")) or "Recipe not found.",
                "use_recipe": lambda a: recipes.use_recipe(a.get("name", ""), self._parse_args(a.get("args_json"))),
                "compile_recipe": lambda a: self._compile_recipe(a.get("name", "")),
                "vault_read": lambda a: self._vault("read", name=a.get("name", "")),
                "vault_write": lambda a: self._vault("write", name=a.get("name", ""), content=a.get("content", "")),
                "vault_search": lambda a: self._vault("search", query=a.get("query", "")),
                "vault_list": lambda a: self._vault("list"),
                "vault_remember": lambda a: self._vault("remember", content=a.get("content", "")),
                "vault_recall": lambda a: self._vault("recall", query=a.get("query", "")),
                "write_output_file": lambda a: self._save_output(a),
            }
        return d

    def _handle_tool(self, tc: Dict[str, Any]) -> str:
        """Handle a tool call from the LLM.
        
        Args:
            tc: Tool call dictionary with 'name' and 'arguments' keys.
            
        Returns:
            Tool execution result as a string.
        """
        name: str = tc["name"]
        args: Dict[str, Any] = tc.get("arguments", {})
        handler: Optional[Callable[[Dict[str, Any]], str]] = self._tool_dispatch().get(name)
        if handler is None:
            return "Unknown tool: " + name
        try:
            return handler(args)
        except Exception as e:
            return "Error running tool %s: %s" % (name, e)

    @staticmethod
    def _vault(action: str, **kw: Any) -> str:
        """Interact with the Obsidian vault.
        
        Args:
            action: Vault action to perform (read, write, search, list, remember, recall).
            **kw: Additional keyword arguments for the action.
            
        Returns:
            Action result as a string.
        """
        from skills import obsidian_memory
        return obsidian_memory.run(action=action, **kw)

    @staticmethod
    def _vcat(action: str, **kw: Any) -> str:
        """Search the vault skill catalog.
        
        Args:
            action: Catalog action to perform (search, list, read).
            **kw: Additional keyword arguments for the action.
            
        Returns:
            Action result as a string.
        """
        from skills import vault_skill_catalog
        return vault_skill_catalog.run(action=action, **kw)

    def _compile_recipe(self, name: str) -> str:
        """Compile a Markdown recipe into a Python skill proposal.
        
        Args:
            name: Name of the recipe to compile.
            
        Returns:
            Recipe content with instructions for creating a skill.
        """
        r: Optional[Dict[str, Any]] = recipes.load_recipe(name)
        if r is None:
            return "Recipe not found."
        return ("RECIPE '%s':\n%s\n\nNow convert this recipe into a Python skill module "
                "(NAME, DESCRIPTION, TRIGGERS, run(**kwargs)->str) that performs the same task, "
                "and call propose_new_skill with the generated code plus an explanation so the human can approve it."
                % (r["name"], r["raw"]))

    def _save_output(self, a: Dict[str, Any]) -> str:
        """Save an output file using the file_output module.
        
        Args:
            a: Arguments dictionary with 'filename', 'content', and optional 'is_base64'.
            
        Returns:
            Success message with file details and download URL.
        """
        result: Dict[str, Any] = file_output.save_file(
            a.get("filename", "output.txt"),
            a.get("content", ""),
            is_base64=a.get("is_base64", False),
        )
        return "File saved: %s (%d bytes). Download at: %s" % (
            result["filename"], result["size"], result["download_url"])

    def _propose_skill(self, args: Dict[str, Any], edit: bool) -> str:
        """Propose creating or editing a skill.
        
        Args:
            args: Arguments dictionary with 'name', 'code', 'explanation', and optional 'description'.
            edit: If True, propose editing an existing skill; otherwise, create a new one.
            
        Returns:
            Proposal status message.
        """
        name: str = args.get("name", "")
        code: str = args.get("code", "")
        explanation: str = args.get("explanation", "")
        title: str = args.get("description", "") or name
        path: str = skills.skill_path(name)
        old: str = skills.read_skill(name) if edit else ""
        change_type: str = "edit" if edit else "create"
        p = proposals.create_proposal(path, old, code, change_type, explanation, title)
        verdict: str = self.approver(p) or ""
        if "approved" in verdict:
            return ("Proposal %s approved and applied. The skill '%s' is now part of your capabilities. "
                    "Call execute_skill with name='%s' to run it." % (p.id, name, name))
        if "rejected" in verdict:
            return "Proposal %s was rejected. No changes were made." % p.id
        return "Proposal %s was updated and is still pending review." % p.id

    def _propose_code(self, args: Dict[str, Any]) -> str:
        """Propose creating or editing a code file.
        
        Args:
            args: Arguments dictionary with 'file_path', 'code', and 'explanation'.
            
        Returns:
            Proposal status message.
        """
        file_path: str = args.get("file_path", "")
        code: str = args.get("code", "")
        explanation: str = args.get("explanation", "")
        root: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_path: str = os.path.abspath(file_path)
        if not (abs_path == root or abs_path.startswith(root + os.sep)):
            return "Refusing to modify files outside the project directory (%s)." % root
        old: str = ""
        if os.path.exists(abs_path):
            with open(abs_path, "r", encoding="utf-8") as f:
                old = f.read()
        p = proposals.create_proposal(abs_path, old, code, "edit" if old else "create", explanation, os.path.basename(abs_path))
        verdict: str = self.approver(p) or ""
        if "approved" in verdict:
            return "Proposal %s approved and applied to %s." % (p.id, abs_path)
        if "rejected" in verdict:
            return "Proposal %s was rejected. No changes were made." % p.id
        return "Proposal %s was updated and is still pending review." % p.id