from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar
import pandas as pd

# Try to import the Cython-accelerated decoder
try:
    from cython_decode import decode_dict_bytes_to_utf8
    _has_cython_decode = True
except ImportError:
    decode_dict_bytes_to_utf8 = None
    _has_cython_decode = False

# Configuration from environment variables
REDIS_CONNECTION_STRING: str = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
REDIS_MAX_CONNECTIONS: int = int(os.getenv("REDIS_MAX_CONNECTIONS", "10"))

# Stream processing defaults
RECORDS: int = int(os.getenv("STREAMENGINE_RECORDS", "10000"))
COUNT: int = int(os.getenv("STREAMENGINE_COUNT", "10"))  # Number of messages the redis connection is to collect at once.
DEFAULT_CONSUMER_GROUP: str = os.getenv("STREAMENGINE_DEFAULT_GROUP", "eventengine")

T = TypeVar('T')

def dataclass_list_to_dataframe(instances: List[Any]) -> pd.DataFrame:
    """
    Convert a list of dataclass instances to a pandas DataFrame.
    """
    if not instances:
        return pd.DataFrame()
    if not is_dataclass(instances[0]):
        raise ValueError("All instances must be dataclasses.")
    return pd.DataFrame([asdict(obj) for obj in instances])

def dataframe_to_dataclass_list(df: pd.DataFrame, cls: Type[T]) -> List[T]:
    """
    Convert a pandas DataFrame to a list of dataclass instances of type cls.

    Args:
        df: Pandas DataFrame to convert
        cls: Dataclass type to convert to

    Returns:
        List of dataclass instances

    Raises:
        ValueError: If cls is not a dataclass or DataFrame is missing required fields
    """
    if not hasattr(cls, '__dataclass_fields__'):
        raise ValueError("cls must be a dataclass type.")

    if df.empty:
        return []

    expected_fields = set(cls.__dataclass_fields__.keys())
    actual_fields = set(df.columns)
    missing = expected_fields - actual_fields

    if missing:
        raise ValueError(f"DataFrame missing required fields: {missing}")

    extra = actual_fields - expected_fields
    if extra:
        import logging
        logging.getLogger(__name__).warning(
            f"DataFrame has extra fields that will be ignored: {extra}"
        )

    # Only use fields that exist in the dataclass
    field_columns = list(cls.__dataclass_fields__.keys())
    return [cls(**{k: row[k] for k in field_columns if k in row})
            for row in df.to_dict(orient='records')]

@dataclass
class Message:
    """
    Message to be sent to redis streams.
    """
    topic: Optional[str] = None
    key: Optional[str] = None
    sent: Optional[float] = None
    received: Optional[float] = None
    consumer_id: Optional[str] = None
    data: Optional[Tuple[str, Dict]] = None

    @property
    def message(self) -> Dict[str, str]:
        """Decode message data from bytes to utf-8 strings (Cython-accelerated if available)."""
        if not self.data:
            return {}
        d = dict(self.data)
        if _has_cython_decode and decode_dict_bytes_to_utf8 is not None:
            return decode_dict_bytes_to_utf8(d)
        # Fallback to pure Python
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in d.items()}

    @property
    def timer(self) -> str:
        """Return a string with the time taken for the task in ms."""
        if self.sent is not None and self.received is not None:
            return f"{self.topic}: task {(float(self.received) - float(self.sent)) * 1000:.2f} ms"
        return ""

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class AppConfig:
    """
    Application configuration dataclass.
    """
    name: str = ""
    to_scan: bool = True
    max_processes: int = 5
    max_threads: int = 5
    webserver_port: int = 8000
    webserver_host: str = "localhost"
    debug: bool = False
    redis_url: str = REDIS_CONNECTION_STRING
    redis_max_connections: int = REDIS_MAX_CONNECTIONS

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.max_processes < 1:
            raise ValueError("max_processes must be >= 1")
        if self.max_threads < 1:
            raise ValueError("max_threads must be >= 1")
        if self.webserver_port < 1 or self.webserver_port > 65535:
            raise ValueError("webserver_port must be between 1 and 65535")
        if self.redis_max_connections < 1:
            raise ValueError("redis_max_connections must be >= 1")

@dataclass
class ConsumerConfig:
    """
    Configuration for a stream consumer agent.
    """
    decorator_type: str
    topic: str
    group: str = DEFAULT_CONSUMER_GROUP
    concurrency: int = 1
    processes: Optional[int] = None
    max_retries: int = 3
    retry_delay_ms: int = 100
    obj_name: Optional[str] = None
    inner_vars: Optional[Any] = None
    mod: Optional[Any] = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.processes is not None and self.processes < 1:
            raise ValueError("processes must be >= 1 if specified")

@dataclass
class TimerConfig:
    """
    Configuration for a timer task.
    """
    decorator_type: str
    t: int
    obj_name: Optional[str] = None
    inner_vars: Optional[Any] = None
    mod: Optional[Any] = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.t < 0:
            raise ValueError("timer interval must be >= 0")

@dataclass
class StreamTopic:
    """
    Stream topic configuration.
    """
    stream: str
    model: str
    group: Optional[str] = None

# --- Cythonization candidates ---
# If you have any CPU-bound data processing, mark here for Cythonization.
# Example:
# def heavy_processing(...):
#     ... # Move to .pyx and use nogil for true parallelism


# Public API
__all__ = [
    # Configuration constants
    "REDIS_CONNECTION_STRING",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_MAX_CONNECTIONS",
    "RECORDS",
    "COUNT",
    "DEFAULT_CONSUMER_GROUP",
    # Utility functions
    "dataclass_list_to_dataframe",
    "dataframe_to_dataclass_list",
    # Dataclasses
    "Message",
    "AppConfig",
    "ConsumerConfig",
    "TimerConfig",
    "StreamTopic",
]


