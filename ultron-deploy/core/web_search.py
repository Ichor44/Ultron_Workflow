"""Async web search with concurrent requests and caching.

Provides non-blocking web search with:
- Async HTTP requests using aiohttp
- Concurrent search across multiple engines
- Response caching with TTL
- Rate limiting
- Fallback to sync requests
"""

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote, urlencode

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from core.cache import TTLCache, get_cache_manager
from core import logging as ultron_logging


# Search cache
_search_cache: TTLCache = TTLCache(maxsize=256, ttl=600.0)  # 10 minute TTL

# Rate limiting
_rate_limit_lock: asyncio.Lock = None if not AIOHTTP_AVAILABLE else asyncio.Lock()
_last_request_time: float = 0
_min_request_interval: float = 0.1  # 100ms between requests


class SearchResult:
    """Search result container."""
    
    def __init__(self, title: str, url: str, snippet: str, engine: str = "unknown") -> None:
        """Initialize search result.
        
        Args:
            title: Result title.
            url: Result URL.
            snippet: Result snippet/description.
            engine: Search engine that returned this result.
        """
        self.title: str = title
        self.url: str = url
        self.snippet: str = snippet
        self.engine: str = engine
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation.
        """
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "engine": self.engine
        }
    
    def __str__(self) -> str:
        """String representation."""
        return f"{self.title}\n   {self.url}\n   {self.snippet}"


class AsyncWebSearch:
    """Async web search with multiple engine support."""
    
    def __init__(self, max_concurrent: int = 5, timeout: float = 10.0) -> None:
        """Initialize async web search.
        
        Args:
            max_concurrent: Maximum concurrent requests.
            timeout: Request timeout in seconds.
        """
        self.max_concurrent: int = max_concurrent
        self.timeout: float = timeout
        self.logger = ultron_logging.get_logger()
    
    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        global _last_request_time
        async with _rate_limit_lock:
            now = time.time()
            elapsed = now - _last_request_time
            if elapsed < _min_request_interval:
                await asyncio.sleep(_min_request_interval - elapsed)
            _last_request_time = time.time()
    
    async def _fetch_url(self, session: 'aiohttp.ClientSession', url: str, 
                         headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Fetch a URL asynchronously.
        
        Args:
            session: aiohttp client session.
            url: URL to fetch.
            headers: Optional request headers.
            
        Returns:
            Response text or None on error.
        """
        try:
            await self._rate_limit()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                if response.status == 200:
                    return await response.text()
                self.logger.warning(f"HTTP {response.status} for {url}")
                return None
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout fetching {url}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_duckduckgo(self, html: str) -> List[SearchResult]:
        """Parse DuckDuckGo HTML results.
        
        Args:
            html: HTML content from DuckDuckGo.
            
        Returns:
            List of search results.
        """
        results: List[SearchResult] = []
        
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
        urls = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html, re.S)
        
        clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
        
        for i in range(min(len(titles), len(urls))):
            title = clean(titles[i])
            url = urls[i] if i < len(urls) else ""
            snippet = clean(snippets[i]) if i < len(snippets) else ""
            
            if title and url:
                results.append(SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    engine="duckduckgo"
                ))
        
        return results
    
    def _parse_bing(self, html: str) -> List[SearchResult]:
        """Parse Bing HTML results.
        
        Args:
            html: HTML content from Bing.
            
        Returns:
            List of search results.
        """
        results: List[SearchResult] = []
        
        # Bing result parsing pattern
        pattern = r'<li class="b_algo"[^>]*>.*?<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>.*?<p[^>]*>(.*?)</p>'
        matches = re.findall(pattern, html, re.S | re.DOTALL)
        
        clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
        
        for url, title, snippet in matches:
            title = clean(title)
            snippet = clean(snippet)
            
            if title and url:
                results.append(SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    engine="bing"
                ))
        
        return results
    
    async def search_duckduckgo(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """Search using DuckDuckGo.
        
        Args:
            query: Search query.
            num_results: Number of results to return.
            
        Returns:
            List of search results.
        """
        if not AIOHTTP_AVAILABLE:
            return self._search_duckduckgo_sync(query, num_results)
        
        cache_key = f"ddg:{query}:{num_results}"
        cached = _search_cache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Ultron/2.0)"}
        
        async with aiohttp.ClientSession() as session:
            html = await self._fetch_url(session, url, headers)
            if html:
                results = self._parse_duckduckgo(html)[:num_results]
                _search_cache.set(cache_key, results)
                return results
        
        return []
    
    def _search_duckduckgo_sync(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """Synchronous DuckDuckGo search fallback.
        
        Args:
            query: Search query.
            num_results: Number of results to return.
            
        Returns:
            List of search results.
        """
        if not REQUESTS_AVAILABLE:
            self.logger.error("Neither aiohttp nor requests available for web search")
            return []
        
        cache_key = f"ddg:{query}:{num_results}"
        cached = _search_cache.get(cache_key)
        if cached:
            return cached
        
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (compatible; Ultron/2.0)"}
            
            resp = requests.post(url, data={"q": query}, timeout=12, headers=headers)
            resp.raise_for_status()
            
            results = self._parse_duckduckgo(resp.text)[:num_results]
            _search_cache.set(cache_key, results)
            return results
        except Exception as e:
            self.logger.error(f"DuckDuckGo search failed: {e}")
            return []
    
    async def search(self, query: str, engines: Optional[List[str]] = None,
                     num_results: int = 5) -> List[SearchResult]:
        """Search across multiple engines.
        
        Args:
            query: Search query.
            engines: List of engines to use (default: ["duckduckgo"]).
            num_results: Number of results per engine.
            
        Returns:
            Combined and deduplicated search results.
        """
        if engines is None:
            engines = ["duckduckgo"]
        
        all_results: List[SearchResult] = []
        
        # Run searches concurrently
        tasks = []
        for engine in engines:
            if engine == "duckduckgo":
                tasks.append(self.search_duckduckgo(query, num_results))
            # Add more engines here as needed
        
        if tasks:
            results_lists = await asyncio.gather(*tasks, return_exceptions=True)
            for results in results_lists:
                if isinstance(results, list):
                    all_results.extend(results)
        
        # Deduplicate by URL
        seen_urls: Set[str] = set()
        unique_results: List[SearchResult] = []
        
        for result in all_results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)
        
        return unique_results[:num_results]
    
    def search_sync(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """Synchronous search wrapper.
        
        Args:
            query: Search query.
            num_results: Number of results to return.
            
        Returns:
            List of search results.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, use sync fallback
                return self._search_duckduckgo_sync(query, num_results)
            else:
                return loop.run_until_complete(self.search(query, num_results=num_results))
        except RuntimeError:
            # No event loop, use sync fallback
            return self._search_duckduckgo_sync(query, num_results)


# Global instance
_search: Optional[AsyncWebSearch] = None


def get_search() -> AsyncWebSearch:
    """Get the global web search instance.
    
    Returns:
        AsyncWebSearch instance.
    """
    global _search
    if _search is None:
        _search = AsyncWebSearch()
    return _search


# ==================== PUBLIC API ====================

async def web_search_async(query: str, num_results: int = 5) -> str:
    """Search the web asynchronously.
    
    Args:
        query: Search query.
        num_results: Number of results to return.
        
    Returns:
        Formatted search results string.
    """
    search = get_search()
    results = await search.search(query, num_results=num_results)
    
    if not results:
        return "No results found."
    
    formatted = []
    for i, result in enumerate(results, 1):
        formatted.append(f"{i}. {result.title}\n   {result.url}\n   {result.snippet}")
    
    return "\n\n".join(formatted)


def web_search_sync(query: str, num_results: int = 5) -> str:
    """Search the web synchronously.
    
    Args:
        query: Search query.
        num_results: Number of results to return.
        
    Returns:
        Formatted search results string.
    """
    search = get_search()
    results = search.search_sync(query, num_results)
    
    if not results:
        return "No results found."
    
    formatted = []
    for i, result in enumerate(results, 1):
        formatted.append(f"{i}. {result.title}\n   {result.url}\n   {result.snippet}")
    
    return "\n\n".join(formatted)


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web (auto-detects async/sync).
    
    Args:
        query: Search query.
        num_results: Number of results to return.
        
    Returns:
        Formatted search results string.
    """
    if AIOHTTP_AVAILABLE:
        return web_search_sync(query, num_results)  # Use sync for backward compatibility
    else:
        return web_search_sync(query, num_results)
