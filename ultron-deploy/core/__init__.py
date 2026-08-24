"""Ultron core module - optimized version.

Exports optimized modules with caching, indexing, and connection pooling.
"""

# Export optimized modules
from core import llm
from core import skills
from core import memory
from core import recipes
from core import proposals
from core import review
from core import file_output
from core import cache
from core import voice
from core import notify
from core import engine
from core import logging as ultron_logging
from core import updater

# Expose key classes
from core.llm import LLM, LLMResponse, LLMUsage, LLMClientPool
from core.skills import list_skills, read_skill, load_skill, execute_skill, write_skill
from core.memory import save_note, recall_note, remember_fact, recall_fact
from core.memory import add_reminder, list_reminders, complete_reminder, due_reminders
from core.recipes import list_recipes, read_recipe, use_recipe, write_recipe
from core.cache import TTLCache, CacheManager, get_cache_manager
from core.engine import Agent, SYSTEM_PROMPT
from core.logging import get_logger, log_performance

__all__ = [
    'llm', 'skills', 'memory', 'recipes', 'proposals',
    'review', 'file_output', 'cache', 'voice', 'notify',
    'engine', 'ultron_logging', 'updater',
    'LLM', 'LLMResponse', 'LLMUsage', 'LLMClientPool',
    'list_skills', 'read_skill', 'load_skill', 'execute_skill', 'write_skill',
    'save_note', 'recall_note', 'remember_fact', 'recall_fact',
    'add_reminder', 'list_reminders', 'complete_reminder', 'due_reminders',
    'list_recipes', 'read_recipe', 'use_recipe', 'write_recipe',
    'TTLCache', 'CacheManager', 'get_cache_manager',
    'Agent', 'SYSTEM_PROMPT',
    'get_logger', 'log_performance',
]
