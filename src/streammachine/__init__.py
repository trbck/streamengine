"""
StreamMachine - Redis Streams Processing Framework

A simple, lightweight Redis Streams processing library built on coredis.
Provides decorator-based agent/timer registration with venusian discovery.
"""

__version__ = "0.1.0"

from .app import App, StreamConsumer
from .models import (
    Message,
    AppConfig,
    ConsumerConfig,
    TimerConfig,
    StreamTopic,
    dataclass_list_to_dataframe,
    dataframe_to_dataclass_list,
)
from .redisapi import RedisConnection
from .storage import Storage

# Optional imports
try:
    from .objstorage.redisobjstore import RedisObjectStorage
except ImportError:
    RedisObjectStorage = None  # type: ignore

try:
    from .cython import decode_dict_bytes_to_utf8, _has_cython_decode
except ImportError:
    decode_dict_bytes_to_utf8 = None  # type: ignore
    _has_cython_decode = False

__all__ = [
    # Version
    "__version__",
    # Core classes
    "App",
    "StreamConsumer",
    "Message",
    "AppConfig",
    "ConsumerConfig",
    "TimerConfig",
    "StreamTopic",
    # Redis
    "RedisConnection",
    # Storage
    "Storage",
    # Utilities
    "dataclass_list_to_dataframe",
    "dataframe_to_dataclass_list",
    # Optional
    "RedisObjectStorage",
    "decode_dict_bytes_to_utf8",
    "_has_cython_decode",
]