"""Structured logging system for Ultron.

Provides JSON-formatted logs with:
- Structured fields for easy parsing
- Log levels and rotation
- Performance tracking
- Request/response logging
- Error context capture
"""

import json
import logging
import logging.handlers
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from contextlib import contextmanager
from functools import wraps
import threading


LOG_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        Args:
            record: Log record to format.
            
        Returns:
            JSON-formatted log string.
        """
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields
        if hasattr(record, 'extra_data'):
            log_entry["data"] = record.extra_data
        
        # Add exception info
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # Add performance data
        if hasattr(record, 'duration_ms'):
            log_entry["duration_ms"] = record.duration_ms
        
        # Add request context
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        
        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable log formatter for development."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors.
        
        Args:
            record: Log record to format.
            
        Returns:
            Colored log string.
        """
        color = self.COLORS.get(record.levelname, '')
        reset = self.RESET
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = record.getMessage()
        
        # Add extra data if present
        extra = ""
        if hasattr(record, 'extra_data'):
            extra = f" | {json.dumps(record.extra_data, default=str)}"
        
        # Add duration if present
        if hasattr(record, 'duration_ms'):
            extra += f" | {record.duration_ms:.2f}ms"
        
        return f"{color}[{timestamp}] {record.levelname:8} {record.name}: {message}{extra}{reset}"


class UltronLogger:
    """Main logger for Ultron with structured logging."""
    
    _instance: Optional['UltronLogger'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'UltronLogger':
        """Singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize the logger."""
        if self._initialized:
            return
        self._initialized = True
        
        os.makedirs(LOG_DIR, exist_ok=True)
        
        # Main logger
        self.logger: logging.Logger = logging.getLogger('ultron')
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        
        # Console handler (text format)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(TextFormatter())
        self.logger.addHandler(console_handler)
        
        # File handler (JSON format, rotated)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "ultron.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(file_handler)
        
        # Error handler (separate file)
        error_handler = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "errors.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(error_handler)
        
        # Performance handler
        perf_handler = logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "performance.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8'
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(JSONFormatter())
        self._perf_handler = perf_handler
        
        # Track request IDs
        self._request_counter: int = 0
        self._request_lock: threading.Lock = threading.Lock()
    
    def get_request_id(self) -> str:
        """Generate a unique request ID.
        
        Returns:
            Unique request identifier.
        """
        with self._request_lock:
            self._request_counter += 1
            return f"req_{self._request_counter}_{int(time.time())}"
    
    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Log a message with extra data.
        
        Args:
            level: Log level (debug, info, warning, error, critical).
            message: Log message.
            **kwargs: Extra fields to include.
        """
        log_level = getattr(logging, level.upper(), logging.INFO)
        record = self.logger.makeRecord(
            name='ultron',
            level=log_level,
            fn='', lno=0, msg=message,
            args=(), exc_info=None
        )
        
        if kwargs:
            record.extra_data = kwargs
        
        self.logger.handle(record)
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self.log('debug', message, **kwargs)
    
    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self.log('info', message, **kwargs)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self.log('warning', message, **kwargs)
    
    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self.log('error', message, **kwargs)
    
    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message."""
        self.log('critical', message, **kwargs)
    
    def log_tool_call(self, tool_name: str, args: Dict[str, Any], 
                      result: str, duration_ms: float, request_id: Optional[str] = None) -> None:
        """Log a tool call.
        
        Args:
            tool_name: Name of the tool called.
            args: Tool arguments.
            result: Tool result.
            duration_ms: Execution time in milliseconds.
            request_id: Optional request ID.
        """
        self.info(
            f"Tool call: {tool_name}",
            tool=tool_name,
            args=args,
            result_length=len(result),
            duration_ms=duration_ms,
            request_id=request_id
        )
    
    def log_llm_call(self, model: str, tokens: int, duration_ms: float,
                     request_id: Optional[str] = None) -> None:
        """Log an LLM API call.
        
        Args:
            model: Model name.
            tokens: Total tokens used.
            duration_ms: API call duration in milliseconds.
            request_id: Optional request ID.
        """
        self.info(
            f"LLM call: {model}",
            model=model,
            tokens=tokens,
            duration_ms=duration_ms,
            request_id=request_id
        )
    
    def log_skill_execution(self, skill_name: str, success: bool,
                           duration_ms: float, error: Optional[str] = None,
                           request_id: Optional[str] = None) -> None:
        """Log skill execution.
        
        Args:
            skill_name: Name of the skill.
            success: Whether execution succeeded.
            duration_ms: Execution time in milliseconds.
            error: Error message if failed.
            request_id: Optional request ID.
        """
        level = 'info' if success else 'error'
        self.log(
            level,
            f"Skill {'executed' if success else 'failed'}: {skill_name}",
            skill=skill_name,
            success=success,
            duration_ms=duration_ms,
            error=error,
            request_id=request_id
        )
    
    def log_request(self, method: str, path: str, status_code: int,
                    duration_ms: float, request_id: Optional[str] = None) -> None:
        """Log HTTP request.
        
        Args:
            method: HTTP method.
            path: Request path.
            status_code: Response status code.
            duration_ms: Request duration in milliseconds.
            request_id: Optional request ID.
        """
        level = 'info' if status_code < 400 else 'warning' if status_code < 500 else 'error'
        self.log(
            level,
            f"{method} {path} -> {status_code}",
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            request_id=request_id
        )
    
    @contextmanager
    def track_performance(self, operation: str, request_id: Optional[str] = None):
        """Context manager to track operation performance.
        
        Args:
            operation: Operation name.
            request_id: Optional request ID.
            
        Yields:
            Dictionary to add extra context.
        """
        start_time = time.perf_counter()
        context_data: Dict[str, Any] = {}
        
        try:
            yield context_data
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            extra = {
                'operation': operation,
                'duration_ms': duration_ms,
                **context_data
            }
            if request_id:
                extra['request_id'] = request_id
            
            self.info(f"Operation completed: {operation}", **extra)
    
    def set_level(self, level: str) -> None:
        """Set the logger level.
        
        Args:
            level: Log level (debug, info, warning, error, critical).
        """
        log_level = getattr(logging, level.upper(), logging.INFO)
        self.logger.setLevel(log_level)
        for handler in self.logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(log_level)


# Global logger instance
_logger: Optional[UltronLogger] = None
_logger_lock: threading.Lock = threading.Lock()


def get_logger() -> UltronLogger:
    """Get the global logger instance.
    
    Returns:
        UltronLogger instance.
    """
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = UltronLogger()
    return _logger


def log(level: str, message: str, **kwargs: Any) -> None:
    """Log a message (convenience function).
    
    Args:
        level: Log level.
        message: Log message.
        **kwargs: Extra fields.
    """
    get_logger().log(level, message, **kwargs)


def log_performance(operation: str):
    """Decorator to log function performance.
    
    Args:
        operation: Operation name for logging.
        
    Returns:
        Decorated function.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger()
            start_time = time.perf_counter()
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    f"Function completed: {func.__name__}",
                    function=func.__name__,
                    operation=operation,
                    duration_ms=duration_ms,
                    success=True
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    f"Function failed: {func.__name__}",
                    function=func.__name__,
                    operation=operation,
                    duration_ms=duration_ms,
                    success=False,
                    error=str(e)
                )
                raise
        return wrapper
    return decorator


# Convenience functions
def debug(message: str, **kwargs: Any) -> None:
    """Log debug message."""
    get_logger().debug(message, **kwargs)

def info(message: str, **kwargs: Any) -> None:
    """Log info message."""
    get_logger().info(message, **kwargs)

def warning(message: str, **kwargs: Any) -> None:
    """Log warning message."""
    get_logger().warning(message, **kwargs)

def error(message: str, **kwargs: Any) -> None:
    """Log error message."""
    get_logger().error(message, **kwargs)

def critical(message: str, **kwargs: Any) -> None:
    """Log critical message."""
    get_logger().critical(message, **kwargs)
