"""High-performance caching layer for Ultron core modules.

Provides LRU cache with TTL support, cache invalidation callbacks,
and thread-safe operations for skill/recipe/memory data.
"""

import time
import threading
from functools import lru_cache, wraps
from typing import Any, Callable, Dict, Optional, TypeVar, Generic
from collections import OrderedDict
import weakref

T = TypeVar('T')


class TTLCache(Generic[T]):
    """Thread-safe LRU cache with TTL (time-to-live) support."""
    
    __slots__ = ('_cache', '_maxsize', '_ttl', '_lock', '_hits', '_misses')
    
    def __init__(self, maxsize: int = 128, ttl: float = 300.0):
        self._cache: OrderedDict[str, tuple[T, float]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[T]:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return value
    
    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        with self._lock:
            expiry = time.time() + (ttl if ttl is not None else self._ttl)
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, expiry)
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)
    
    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
    
    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all keys starting with prefix."""
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
            return len(keys_to_delete)
    
    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hit_rate": self._hits / total if total > 0 else 0.0
            }


class CacheManager:
    """Centralized cache manager for all core modules."""
    
    _instance: Optional['CacheManager'] = None
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
        
        # Caches for different data types
        self.skills = TTLCache[Dict](maxsize=256, ttl=60.0)
        self.recipes = TTLCache[Dict](maxsize=128, ttl=60.0)
        self.memory = TTLCache[Dict](maxsize=64, ttl=30.0)
        self.vault = TTLCache[str](maxsize=256, ttl=120.0)
        self.config = TTLCache[Dict](maxsize=16, ttl=300.0)
        self.mcp_status = TTLCache[Dict](maxsize=32, ttl=30.0)
        
        # Invalidation callbacks
        self._invalidation_callbacks: Dict[str, list[Callable]] = {
            'skills': [],
            'recipes': [],
            'memory': [],
            'vault': [],
            'config': [],
            'mcp': [],
        }
    
    def register_invalidation(self, cache_name: str, callback: Callable) -> None:
        """Register a callback to be called when cache is invalidated."""
        if cache_name in self._invalidation_callbacks:
            self._invalidation_callbacks[cache_name].append(callback)
    
    def invalidate(self, cache_name: str, key: Optional[str] = None) -> int:
        """Invalidate cache entries and trigger callbacks."""
        cache = getattr(self, 'mcp_status' if cache_name == 'mcp' else cache_name, None)
        if not isinstance(cache, TTLCache):
            return 0
        if key:
            count = 1 if cache.delete(key) else 0
        else:
            count = len(cache._cache)
            cache.clear()
        
        # Trigger callbacks
        for cb in self._invalidation_callbacks.get(cache_name, []):
            try:
                cb(key)
            except Exception:
                pass
        
        return count
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all caches."""
        return {
            name: cache.stats 
            for name, cache in [
                ('skills', self.skills),
                ('recipes', self.recipes),
                ('memory', self.memory),
                ('vault', self.vault),
                ('config', self.config),
                ('mcp', self.mcp_status),
            ]
        }


# Global cache manager instance
_cache_manager = CacheManager()


def get_cache_manager() -> CacheManager:
    """Get the global cache manager instance."""
    return _cache_manager


def cached(cache_name: str, key_func: Optional[Callable] = None, ttl: Optional[float] = None):
    """Decorator for caching function results.
    
    Args:
        cache_name: Name of cache to use ('skills', 'recipes', 'memory', 'vault', 'config', 'mcp')
        key_func: Function to generate cache key from args/kwargs. Defaults to str(args)+str(kwargs)
        ttl: Override default TTL for this function
    """
    def decorator(func: Callable) -> Callable:
        manager = get_cache_manager()
        cache_map = {
            'skills': manager.skills,
            'recipes': manager.recipes,
            'memory': manager.memory,
            'vault': manager.vault,
            'config': manager.config,
            'mcp': manager.mcp_status,
        }
        cache = cache_map.get(cache_name)
        if cache is None:
            raise ValueError(f"Unknown cache: {cache_name}")
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            
            result = cache.get(key)
            if result is not None:
                return result
            
            result = func(*args, **kwargs)
            cache.set(key, result, ttl)
            return result
        
        # Attach cache management methods
        wrapper.cache = cache
        wrapper.invalidate = lambda k=None: cache.delete(k) if k else cache.clear()
        wrapper.invalidate_prefix = lambda p: cache.invalidate_prefix(p)
        return wrapper
    
    return decorator


# Convenience decorators for common caches
def cached_skill(func: Callable) -> Callable:
    return cached('skills')(func)

def cached_recipe(func: Callable) -> Callable:
    return cached('recipes')(func)

def cached_memory(func: Callable) -> Callable:
    return cached('memory')(func)

def cached_vault(func: Callable) -> Callable:
    return cached('vault')(func)

def cached_config(func: Callable) -> Callable:
    return cached('config')(func)

def cached_mcp(func: Callable) -> Callable:
    return cached('mcp')(func)


def invalidate_on_change(cache_name: str):
    """Decorator to register a function as an invalidation callback."""
    def decorator(func: Callable) -> Callable:
        manager = get_cache_manager()
        manager.register_invalidation(cache_name, func)
        return func
    return decorator


class Memoize:
    """Simple memoization decorator with optional TTL."""
    
    def __init__(self, ttl: float = 300.0, maxsize: int = 128):
        self.ttl = ttl
        self.maxsize = maxsize
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)
    
    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__qualname__}:{args}:{tuple(sorted(kwargs.items()))}"
            result = self._cache.get(key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            self._cache.set(key, result)
            return result
        wrapper.cache = self._cache
        wrapper.clear_cache = self._cache.clear
        return wrapper


# Performance timing utilities
import contextlib

@contextlib.contextmanager
def timed(operation: str):
    """Context manager for timing operations."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        # Could log to a metrics system here
        pass


class PerformanceMonitor:
    """Lightweight performance monitoring."""
    
    def __init__(self):
        self._timings: Dict[str, list[float]] = {}
        self._lock = threading.Lock()
    
    def record(self, operation: str, duration_ms: float) -> None:
        with self._lock:
            if operation not in self._timings:
                self._timings[operation] = []
            self._timings[operation].append(duration_ms)
            # Keep only last 1000 measurements
            if len(self._timings[operation]) > 1000:
                self._timings[operation] = self._timings[operation][-1000:]
    
    def get_stats(self, operation: str) -> Dict[str, float]:
        with self._lock:
            times = self._timings.get(operation, [])
            if not times:
                return {}
            return {
                "count": len(times),
                "min": min(times),
                "max": max(times),
                "avg": sum(times) / len(times),
                "p50": sorted(times)[len(times) // 2],
                "p95": sorted(times)[int(len(times) * 0.95)],
                "p99": sorted(times)[int(len(times) * 0.99)],
            }
    
    def get_all_stats(self) -> Dict[str, Dict]:
        with self._lock:
            return {op: self.get_stats(op) for op in self._timings}


_performance_monitor = PerformanceMonitor()


def get_performance_monitor() -> PerformanceMonitor:
    return _performance_monitor


def monitor(operation: str):
    """Decorator to monitor function execution time."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                _performance_monitor.record(operation, elapsed)
        return wrapper
    return decorator