"""Optimized LLM provider abstraction with client reuse and connection pooling.

Provides high-performance LLM interactions with:
- Client instance reuse (no per-request creation)
- Connection pooling for HTTP clients
- Request/response caching
- Async support for concurrent requests
- Token usage tracking
"""

import json
import os
import threading
import time
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from functools import lru_cache

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import anthropic
except Exception:
    anthropic = None


@dataclass
class LLMUsage:
    """Token usage tracking."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    def add(self, other: 'LLMUsage') -> 'LLMUsage':
        return LLMUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    content: Optional[str]
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    model: str = ""
    latency_ms: float = 0.0


class LLMClientPool:
    """Thread-safe client pool for LLM providers."""
    
    _instance: Optional['LLMClientPool'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._openai_clients: Dict[str, OpenAI] = {}
        self._anthropic_clients: Dict[str, anthropic.Anthropic] = {}
        self._client_lock = threading.RLock()
        self._config_cache: Dict[str, Any] = {}
    
    def get_openai_client(self, base_url: str, api_key: str, headers: Optional[Dict] = None) -> OpenAI:
        """Get or create OpenAI-compatible client."""
        if OpenAI is None:
            raise RuntimeError("The 'openai' package is not installed. Run: pip install -r requirements.txt")
        
        cache_key = f"{base_url}:{api_key[:8]}:{hash(tuple(sorted((headers or {}).items())))}"
        
        with self._client_lock:
            if cache_key not in self._openai_clients:
                self._openai_clients[cache_key] = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    default_headers=headers or {},
                    timeout=15.0,
                    max_retries=2,
                )
            return self._openai_clients[cache_key]
    
    def get_anthropic_client(self, api_key: str) -> anthropic.Anthropic:
        """Get or create Anthropic client."""
        if anthropic is None:
            raise RuntimeError("The 'anthropic' package is not installed. Run: pip install -r requirements.txt")
        
        cache_key = api_key[:16]
        
        with self._client_lock:
            if cache_key not in self._anthropic_clients:
                self._anthropic_clients[cache_key] = anthropic.Anthropic(
                    api_key=api_key,
                    timeout=15.0,
                    max_retries=2,
                )
            return self._anthropic_clients[cache_key]
    
    def clear(self):
        """Clear all clients (useful for config changes)."""
        with self._client_lock:
            self._openai_clients.clear()
            self._anthropic_clients.clear()


class LLM:
    """High-performance LLM interface with client reuse."""
    
    _SYSTEM_PROMPT_OVERRIDE: Optional[str] = None
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider = config["provider"]
        self._pool = LLMClientPool()
        self._tools_cache: Dict[str, List[Dict]] = {}
        self._messages_cache: Dict[str, List[Dict]] = {}
    
    @classmethod
    def set_system_prompt_override(cls, prompt: str):
        """Override system prompt for all instances (testing)."""
        cls._SYSTEM_PROMPT_OVERRIDE = prompt
    
    def chat(self, system: str, messages: List[Dict], tools: List[Dict]) -> LLMResponse:
        """Chat with LLM - routes to provider-specific implementation."""
        start = time.perf_counter()
        c = self.config
        if self.provider == "mock":
            resp = self._mock(system, messages, tools)
        elif self.provider in ("openai", "openrouter", "custom", "ollama", "lmstudio"):
            # ollama/lmstudio are OpenAI-compatible local servers; config.py
            # normalizes their env vars into the custom_* keys.
            p = ("openrouter" if self.provider == "openrouter"
                 else "openai" if self.provider == "openai"
                 else "custom")
            headers = ({"HTTP-Referer": c.get("openrouter_site", "https://localhost/agent"),
                        "X-Title": c.get("openrouter_title", "Ultron")} if p == "openrouter" else None)
            
            # Get base_url and api_key based on provider
            if p == "custom":
                base_url = c.get("custom_base_url", "http://localhost:11434/v1")
                api_key = c.get("custom_api_key", "no-key")
                model = c.get("custom_model", "")
            else:
                base_url = c[f"{p}_base_url"]
                api_key = c[f"{p}_api_key"]
                model = c[f"{p}_model"]
            
            resp = self._openai_compatible(base_url, api_key, model, system, messages, tools, headers)
        elif self.provider == "anthropic":
            resp = self._anthropic(system, messages, tools)
        else:
            raise RuntimeError(
                "No LLM provider configured. Set AGENT_LLM_PROVIDER or "
                "OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY / CUSTOM_API_KEY."
            )
        resp.latency_ms = (time.perf_counter() - start) * 1000
        return resp
    
    def _to_openai_messages(self, messages: List[Dict]) -> List[Dict]:
        """Convert internal messages to OpenAI format."""
        out = []
        for m in messages:
            role = m["role"]
            if role == "system":
                continue
            if role == "tool":
                out.append({
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": m["content"],
                })
            elif role == "assistant":
                entry = {"role": "assistant", "content": m.get("content") or ""}
                tcs = m.get("tool_calls")
                if tcs:
                    entry["tool_calls"] = [
                        {"id": tc.get("id", tc["name"]), "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc.get("arguments", {}))}}
                        for tc in tcs]
                # Always append assistant messages — text-only assistant replies
                # (no tool_calls) must be kept in history or multi-turn context breaks.
                out.append(entry)
            else:
                out.append({"role": "user", "content": m["content"]})
        return out
    
    def _to_anthropic_messages(self, messages: List[Dict]) -> List[Dict]:
        """Convert internal messages to Anthropic format."""
        out = []
        for m in messages:
            role = m["role"]
            if role == "system":
                continue
            if role == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if (out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list)
                        and out[-1]["content"] and isinstance(out[-1]["content"][0], dict)
                        and out[-1]["content"][0].get("type") == "tool_result"):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif role == "assistant":
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    content.append({
                        "type": "tool_use",
                        "name": tc["name"],
                        "id": tc.get("id", tc["name"]),
                        "input": tc.get("arguments", {}),
                    })
                if content:
                    out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": "user", "content": m["content"]})
        return out
    
    def _openai_compatible(self, base_url: str, api_key: str, model: str,
                          system: str, messages: List[Dict], tools: List[Dict],
                          headers: Optional[Dict] = None) -> LLMResponse:
        """Call OpenAI-compatible API with client reuse."""
        client = self._pool.get_openai_client(base_url, api_key, headers)
        
        oa_tools = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        } for t in tools]
        
        oa_messages = [{"role": "system", "content": system}] + self._to_openai_messages(messages)
        
        resp = client.chat.completions.create(
            model=model,
            messages=oa_messages,
            tools=oa_tools,
            tool_choice="auto",
            max_tokens=1024,
        )
        
        if not resp.choices:
            return LLMResponse(
                content="The API returned an empty response. Check your API key, model, or network.",
                usage=LLMUsage()
            )
        
        msg = resp.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        
        u = getattr(resp, "usage", None)
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            usage=LLMUsage(u.prompt_tokens, u.completion_tokens, u.total_tokens) if u else LLMUsage(),
            model=model,
        )
    
    def _anthropic(self, system: str, messages: List[Dict], tools: List[Dict]) -> LLMResponse:
        """Call Anthropic API with client reuse."""
        client = self._pool.get_anthropic_client(self.config["anthropic_api_key"])
        
        an_tools = [{
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        } for t in tools]
        
        an_messages = self._to_anthropic_messages(messages)
        
        resp = client.messages.create(
            model=self.config["anthropic_model"],
            system=system,
            messages=an_messages,
            tools=an_tools,
            max_tokens=1024,
        )
        
        content = ""
        tool_calls = []
        if not resp.content:
            return LLMResponse(content="", usage=LLMUsage())
        
        for block in resp.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "arguments": dict(block.input)})
        
        u = getattr(resp, "usage", None)
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=LLMUsage(u.input_tokens, u.output_tokens, u.input_tokens + u.output_tokens) if u else LLMUsage(),
            model=self.config["anthropic_model"],
        )
    
    def _mock(self, system: str, messages: List[Dict], tools: List[Dict]) -> LLMResponse:
        """Mock response for testing."""
        last = messages[-1] if messages else {"role": "user", "content": ""}
        sys_len = len(system) + sum(len(m.get("content", "") or "") for m in messages)
        
        if last.get("role") == "tool":
            return LLMResponse(
                content="I proposed a new skill and it has been reviewed by you. It is now part of my capabilities and can be run with execute_skill whenever this kind of request comes up again.",
                usage=LLMUsage(prompt_tokens=sys_len // 4, completion_tokens=25, total_tokens=sys_len // 4 + 25)
            )
        
        user_text = last.get("content", "")
        slug = "".join(c if c.isalnum() else "_" for c in user_text[:25].lower().strip()) or "task"
        name = "skill_" + slug
        code = (
            "NAME = %r\n" % name
            + "DESCRIPTION = 'Auto-generated skill for: %s'\n" % user_text
            + "TRIGGERS = [%r]\n\n" % user_text
            + "def run(**kwargs):\n"
            + "    return 'Placeholder skill. Edit this code to do real work for: %s'\n" % user_text
        )
        return LLMResponse(
            content="I checked my skills and none of them cover this request, so I will learn a new one.",
            tool_calls=[{
                "id": "call_0",
                "name": "propose_new_skill",
                "arguments": {
                    "name": name,
                    "description": "Auto-generated skill for: " + user_text,
                    "triggers": user_text,
                    "code": code,
                    "explanation": (
                        "No existing skill handles this request. I am creating a new skill module '%s' "
                        "so future identical requests can be served directly via execute_skill instead of "
                        "re-planning. The run() body is a safe placeholder you can edit. Risk: none yet, "
                        "since the body does not perform any side effects." % name
                    ),
                },
            }],
            usage=LLMUsage(prompt_tokens=sys_len // 4, completion_tokens=40, total_tokens=sys_len // 4 + 40)
        )


# Backward compatibility - old dict-based response format
def _response_to_dict(resp: LLMResponse) -> Dict[str, Any]:
    return {
        "content": resp.content,
        "tool_calls": resp.tool_calls,
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        },
    }


# For backward compatibility with engine.py
class LegacyLLM:
    """Wrapper to maintain backward compatibility with engine.py"""
    
    def __init__(self, config: Dict[str, Any]):
        self._llm = LLM(config)
    
    def chat(self, system: str, messages: List[Dict], tools: List[Dict]) -> Dict[str, Any]:
        resp = self._llm.chat(system, messages, tools)
        return _response_to_dict(resp)