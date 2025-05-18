import json
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

# Constants for Redis connection and stream processing
REDIS_CONNECTION_STRING: str = "redis://localhost:6379"
RECORDS: int = 10000
COUNT: int = 10  # Number of messages the redis connection is to collect at once.

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
    """
    if not hasattr(cls, '__dataclass_fields__'):
        raise ValueError("cls must be a dataclass type.")
    return [cls(**row) for row in df.to_dict(orient='records')]

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

@dataclass
class ConsumerConfig:
    """
    Configuration for a stream consumer agent.
    """
    decorator_type: str
    topic: str
    group: str = "eventengine"
    concurrency: int = 1
    processes: Optional[int] = None
    obj_name: Optional[str] = None
    inner_vars: Optional[Any] = None
    mod: Optional[Any] = None

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


