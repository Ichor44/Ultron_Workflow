"""
API Gateway for Ultron.

A single, unified entry point for all external data calls that skills and
plugins may need.  Responsibilities:

* **Request routing** – directs a high‑level request (e.g. ``search_web``,
  ``scrape_url``, ``get_disease_info``) to the appropriate backend
  (Firecrawl, BioMCP, Obsidian, etc.).
* **Authentication** – reads API keys from the environment once at startup
  and injects them into backend calls; skills never see raw keys.
* **Rate limiting** – simple in‑memory counter per backend; configurable
  max calls per minute to avoid hitting provider limits.
* **Caching** – time‑to‑live (TTL) cache per endpoint so repeated queries
  hit the local store instead of the external service (reduces latency &
  cost).
* **Normalization** – every backend call returns a standardized dict shape:
  ``{ "result": <data>, "source": "<backend>", "elapsed": <seconds>, "cache": <bool> }*.
* **Observability** – logs each call with latency, success/failure, and
  cache hit/miss metadata – useful for debugging and cost tracking.
* **Semantic memory hook** – automatically stores the result (or a summary)
  in the long‑term semantic memory so future queries can benefit from prior
  knowledge.

**Standardized response format**

````python
{
    "result": ...,                # backend‑specific data (usually dict or str)
    "source": "firecrawl|biomcp|obsidian|...",
    "elapsed": 0.42,              # seconds spent in the backend
    "cache": true|false,          # whether the result came from cache
    "metadata": { ... }           # optional extra fields (e.g. raw API payload)
}
````

**How to use**

From a skill or plugin:

````python
from core.api_gateway import gateway

resp = gateway.search_web("latest kinase inhibitor clinical trial")
# resp["result"] contains the search results, resp["source"] == "firecrawl"
````

or

````python
resp = gateway.get_biomcp_disease("DOID:123")
````

**Built‑in endpoints**

| Endpoint                | Backend                | Typical args                                 |
|------------------------|------------------------|----------------------------------------------|
| ``search_web(query)``  | Firecrawl `/search`    | ``query`` (str)                               |
| ``scrape_url(url)``    | Firecrawl `/scrape`    | ``url`` (str)                                 |
| ``crawl_site(url)``    | Firecrawl `/crawl`     | ``url`` (str), optional ``max_depth``, ``limit`` |
| ``get_disease(did)``   | BioMCP `disease_get`   | ``disease_id`` (str)                         |
| ``get_gene(sym)``      | BioMCP `gene_get`      | ``gene_symbol`` (str)                        |
| ``get_drug(name)``     | BioMCP `drug_get`      | ``drug_name`` (str)                          |
| ``obsidian_read(note)``| Obsidian vault         | ``filename`` (str)                           |
| ``list_skills()``      | Plugin system          | optional ``category`` filter                 |

**Configuration** (environment variables, .env)

* ``FIRECRAWL_API_KEY`` – required for any Firecrawl call.
* ``BIOMCP_TOKEN`` – optional token if the BioMCP backend requires auth.
* ``GATEWAY_CACHE_TTL_SECONDS`` – default TTL for cache entries (default 300).
* ``GATEWAY_RATE_LIMIT_PER_MINUTE`` – max calls per minute per backend (default 60).

**Future extensions**

* Add a ``/interact`` path for JavaScript‑heavy sites (Firecrawl interact).
* Plug in a Redis‑backed cache for larger-scale deployments.
* Integrate with a distributed rate‑limiter (e.g. token bucket in Redis).
* Expose Prometheus metrics for latency and error rates.
"""

import os
import time
import json
import logging
from typing import Any, Dict, Optional, Callable, TypeVar

from core.semantic_memory import SemanticMemory

# ---------------------------------------------------------------------------
# Simple in‑memory rate limiter (good enough for a single-process agent).
# ---------------------------------------------------------------------------
_RATE_LIMIT_STATE: Dict[str, Dict[str, Any]] = {}
_RATE_LIMIT_LOCK = __import__("threading").Lock()  # simplified


def _check_rate_limit(key: str, per_minute: int) -> bool:
    """Return True if the call is allowed, False if rate‑limited."""
    now = time.time()
    with _RATE_LIMIT_LOCK:
        entry = _RATE_LIMIT_STATE.get(key, {"count": 0, "reset": now})
        if now - entry["reset"] > 60:
            # Reset window
            entry = {"count": 0, "reset": now}
        if entry["count"] >= per_minute:
            return False
        entry["count"] += 1
        _RATE_LIMIT_STATE[key] = entry
        return True


# ---------------------------------------------------------------------------
# TTL cache (simple dict).  Key is ``(endpoint_name, hash_of_args)``.
# ---------------------------------------------------------------------------
_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = int(os.getenv("GATEWAY_CACHE_TTL_SECONDS", "300"))


def _cached(key: str) -> Optional[Dict[str, Any]]:
    """Return cached result if still valid, else None."""
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        entry["hits"] += 1
        return entry["value"]
    # Remove stale
    if entry:
        _cache.pop(key, None)
    return None


def _set_cache(key: str, value: Dict[str, Any]) -> None:
    _cache[key] = {"value": value, "ts": time.time(), "hits": 0}


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gateway class – holds state (rate limits, cache, memory) and provides
# the public methods that skills call.
# ---------------------------------------------------------------------------


class APIGateway:
    """Unified entry point for all external data operations."""

    def __init__(self):
        self.memory: SemanticMemory = SemanticMemory()
        # Firecrawl key – required
        self.firecrawl_key = os.getenv("FIRECRAWL_API_KEY")
        if not self.firecrawl_key:
            LOGGER.warning("FIRECRAWL_API_KEY not set; Firecrawl calls will fail.")
        # BioMCP optional token
        self.biomcp_token = os.getenv("BIOMCP_TOKEN")
        # Rate‑limit defaults (per‑minute) – can be overridden per‑method
        self.default_rate_limit = int(os.getenv("GATEWAY_RATE_LIMIT_PER_MINUTE", "60"))

    # ------------------------------------------------------------------
    # Generic helper that wraps a backend call with rate‑limit, cache,
    # timing, memory storage, and error handling.
    # ------------------------------------------------------------------
    def _execute(
        self,
        name: str,
        backend_func: Callable[[], Any],
        cache_key_extra: str = "",
        rate_key_prefix: str = "",
    ) -> Dict[str, Any]:
        """
        Internal wrapper.

        Parameters
        ----------
        name : str
            Human‑readable endpoint name (used for caching & logging).
        backend_func : callable
            Zero‑argument callable that performs the actual backend request
            and returns whatever the backend returns.
        cache_key_extra : str
            Additional string appended to the cache key (e.g. the query text).
        rate_key_prefix : str
            Prefix for the rate‑limit counter (different backends can have
            separate counters).
        """
        start = time.time()
        # 1️⃣ Check cache
        cache_key = f"{name}:{cache_key_extra}"
        cached = _cached(cache_key)
        if cached is not None:
            elapsed = time.time() - start
            LOGGER.info("%s returned cached result (%.3fs)", name, elapsed)
            # Still store in memory for posterity
            self.memory.add_text(
                json.dumps(cached["result"]),
                metadata={"source": name, "cached": True, "elapsed": elapsed},
            )
            return {
                "result": cached["result"],
                "source": name,
                "elapsed": elapsed,
                "cache": True,
                "metadata": cached.get("meta", {}),
            }

        # 2️⃣ Rate limit
        rate_key = f"{rate_key_prefix}:{name}"
        if not _check_rate_limit(rate_key, self.default_rate_limit):
            LOGGER.warning("Rate limit exceeded for %s", name)
            return {
                "error": "rate_limit_exceeded",
                "source": name,
                "elapsed": time.time() - start,
                "cache": False,
            }

        # 3️⃣ Run the backend
        try:
            result = backend_func()
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Backend %s failed", name)
            elapsed = time.time() - start
            return {
                "error": str(exc),
                "source": name,
                "elapsed": elapsed,
                "cache": False,
            }

        elapsed = time.time() - start

        # 4️⃣ Cache the result (even if it's an error object, so we don't hammer the service)
        _set_cache(cache_key, {"result": result, "meta": {"elapsed": elapsed}})

        # 5️⃣ Store in semantic memory (summary).  We store the JSON‑serialisable
        #    result so future queries can retrieve prior knowledge.
        try:
            self.memory.add_text(
                json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                metadata={"source": name, "cached": False, "elapsed": elapsed},
            )
        except Exception:  # pragma: no cover
            LOGGER.debug("Failed to store result in semantic memory", exc_info=True)

        # 6️⃣ Return normalized response
        return {
            "result": result,
            "source": name,
            "elapsed": elapsed,
            "cache": False,
            "metadata": {},
        }

    # ------------------------------------------------------------------
    # High‑level endpoints
    # ------------------------------------------------------------------

    def search_web(self, query: str, *, max_results: int = 10) -> Dict[str, Any]:
        """
        Search the web via Firecrawl.

        Parameters
        ----------
        query : str
            The user's search query.
        max_results : int
            Desired number of results (passed to Firecrawl ``--limit``).

        Returns
        -------
        dict
            Normalized response (see class docstring).
        """
        def _backend():
            # Firecrawl search – we use the firecrawl CLI via its Python SDK
            # or the underlying skill.  Here we call the existing skill function.
            from skills.web_crawler import run as fc_run
            # The skill expects a query and optional limit; we pass them via kwargs
            # but our runner only forwards args on command line.  For simplicity we
            # invoke the CLI directly.
            import subprocess
            cmd = [
                "firecrawl",
                "search",
                query,
                "--limit",
                str(max_results),
                "--json",
            ]
            env = os.environ.copy()
            if self.firecrawl_key:
                env["FIRECRAWL_API_KEY"] = self.firecrawl_key
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(f"Firecrawl search failed: {result.stderr}")
            # Return parsed JSON if possible
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return result.stdout

        return self._execute(
            "search_web",
            _backend,
            cache_key_extra=query,
            rate_key_prefix="firecrawl",
        )

    def scrape_url(self, url: str) -> Dict[str, Any]:
        """
        Scrape a single URL via Firecrawl.

        Parameters
        ----------
        url : str
            The target URL.

        Returns
        -------
        dict
            Normalized response.
        """
        def _backend():
            import subprocess
            cmd = ["firecrawl", "scrape", url, "-f", "markdown", "-o", "/dev/stdout"]
            env = os.environ.copy()
            if self.firecrawl_key:
                env["FIRECRAWL_API_KEY"] = self.firecrawl_key
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(f"Firecrawl scrape failed: {result.stderr}")
            return result.stdout

        return self._execute("scrape_url", _backend, cache_key_extra=url, rate_key_prefix="firecrawl")

    def crawl_site(
        self,
        url: str,
        *,
        max_depth: int = 3,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Bulk‑crawl a website section.

        Parameters
        ----------
        url : str
            Root URL to crawl.
        max_depth : int
            Maximum depth to follow.
        limit : int
            Max number of pages to extract.

        Returns
        -------
        dict
            Normalized response.
        """
        def _backend():
            import subprocess
            cmd = [
                "firecrawl",
                "crawl",
                url,
                "--limit",
                str(limit),
                "--max-depth",
                str(max_depth),
                "--json",
            ]
            env = os.environ.copy()
            if self.firecrawl_key:
                env["FIRECRAWL_API_KEY"] = self.firecrawl_key
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=300
            )
            if result.returncode != 0:
                raise RuntimeError(f"Firecrawl crawl failed: {result.stderr}")
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return result.stdout

        return self._execute(
            "crawl_site",
            _backend,
            cache_key_extra=f"{url}:{max_depth}:{limit}",
            rate_key_prefix="firecrawl",
        )

    def get_disease(self, disease_id: str) -> Dict[str, Any]:
        """
        Retrieve disease information via BioMCP.

        Parameters
        ----------
        disease_id : str
            Disease ID (e.g. ``"DOID:123"`` or a name that ``biomcp_disease_search``
            can resolve).

        Returns
        -------
        dict
            Normalized response.
        """
        def _backend():
            from biomcp_disease_get import get_disease as bg_get
            # The biomcp API we have takes a disease_id and returns a dict.
            # We'll call the low‑level function directly.
            from core.biomcp_bridge import get_disease_info  # hypothetical bridge
            # For now, fall back to the biomcp library call.
            import json
            # Use the biomcp library's disease_get
            from biomcp import disease_get
            data = disease_get(disease_id=disease_id)  # type: ignore
            return data

        return self._execute(
            "get_disease",
            _backend,
            cache_key_extra=disease_id,
            rate_key_prefix="biomcp",
        )

    def get_gene(self, gene_symbol: str) -> Dict[str, Any]:
        """
        Retrieve gene information via BioMCP.

        Parameters
        ----------
        gene_symbol : str
            Official HGNC gene symbol (e.g. ``"TP53"``).

        Returns
        -------
        dict
            Normalized response.
        """
        def _backend():
            from biomcp import gene_get  # type: ignore
            data = gene_get(symbol=gene_symbol)
            return data

        return self._execute(
            "get_gene",
            _backend,
            cache_key_extra=gene_symbol,
            rate_key_prefix="biomcp",
        )

    def get_drug(self, drug_name: str) -> Dict[str, Any]:
        """
        Retrieve drug information via BioMCP.

        Parameters
        ----------
        drug_name : str
            Lower‑case drug name (e.g. ``"aspirin"``).

        Returns
        -------
        dict
            Normalized response.
        """
        def _backend():
            from biomcp import drug_get  # type: ignore
            data = drug_get(name=drug_name)
            return data

        return self._execute(
            "get_drug",
            _backend,
            cache_key_extra=drug_name,
            rate_key_prefix="biomcp",
        )

    def obsidian_read(self, filename: str, vault: str = "default") -> Dict[str, Any]:
        """
        Read a note from the Obsidian vault.

        Parameters
        ----------
        filename : str
            Note name (``*.md`` optional).
        vault : str
            Vault name as recognised by the Obsidian tools.

        Returns
        -------
        dict
            Normalized response.
        """
        def _backend():
            from core.obsidian_tools import read_note  # lazy import
            # Ensure .md extension
            note = filename if filename.endswith(".md") else filename + ".md"
            content = read_note(vault, note)
            return content if content else ""

        return self._execute(
            "obsidian_read",
            _backend,
            cache_key_extra=f"{vault}:{filename}",
            rate_key_prefix="obsidian",
        )

    def list_skills(self, category: str = "") -> Dict[str, Any]:
        """
        List registered skills (core + plugins).

        Parameters
        ----------
        category : str
            Optional category filter.

        Returns
        -------
        dict
            Normalized response containing a list of skill summaries.
        """
        from core.plugin_system import PluginSystem

        # Scan plugins to get the latest registry
        PluginSystem.scan()

        # Gather core skill names from the skills package
        import skills as skills_pkg
        core_skills = [
            name
            for name in dir(skills_pkg)
            if not name.startswith("_") and callable(getattr(skills_pkg, name))
        ]

        # Gather plugin skill names from the registry
        plugin_skills: List[str] = []
        for full_name, info in PluginSystem._REGISTERED.items():
            # Strip the "plugin:" prefix and possible ":<skill>" suffix
            base = full_name.split(":")[1]  # plugin:<plugin>:<skill>
            skill_name = base.split(":")[-1]
            plugin_skills.append(skill_name)

        all_skills = core_skills + plugin_skills

        if category:
            all_skills = [s for s in all_skills if s.lower().startswith(category.lower())]

        # Build brief summaries – we just use the docstring if available
        summaries: List[Dict[str, Any]] = []
        for s in all_skills:
            try:
                mod = __import__(f"skills.{s}", fromlist=[s])
                doc = (mod.__doc__ or "").split("\n")[0][:80]
            except Exception:
                doc = ""
            summaries.append({"name": s, "description": doc})

        return {
            "result": {"skills": summaries},
            "source": "skill_catalog",
            "elapsed": 0.0,
            "cache": False,
            "metadata": {"total": len(all_skills)},
        }

# ---------------------------------------------------------------------------
# Module‑level convenience instance – most skills will just use ``gateway``.
# ---------------------------------------------------------------------------
gateway = APIGateway()