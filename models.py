
import json
from dataclasses import asdict, dataclass, field
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

#import msgpack
import pandas as pd

REDIS_CONNECTION_STRING = "redis://localhost:6379"
RECORDS = 10000
COUNT = 10  # Number of messages the redis connection is to collect at once.


    
@dataclass()
class Message:
    """
    Message to be send to redis streams.
    """
    topic: str = None
    key: str = None
    sent: float = None
    received: float = None
    consumer_id: str = None
    data: Optional[Tuple[str, Dict]] = None
    
    @property
    def message(self):
        return {k.decode("utf-8"): v.decode("utf-8") for k,v in dict(self.data).items()}
    
    @property
    def timer(self):
        return (f"{self.topic}: task {(float(self.received) - float(self.sent))*1000} ms")
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    #def to_msgpack(self):
    #    return msgpack.packb(self.to_dict())
    
    #def from_msgpack(packed):
    #    return msgpack.unpackb(packed)

    
@dataclass()
class AppConfig:
    name: str = ""
    to_scan: bool = True
    max_processes: int = 5
    max_threads: int = 5

    webserver_port: int = 8000
    webserver_host: str = "localhost"
    debug: bool = False


@dataclass()
class ConsumerConfig:
    decorator_type: str
    topic: str
    group: str = "eventengine"
    concurrency: int = 1
    processes: int = None
    obj_name: str = None
    inner_vars: object = None
    mod: object = None


@dataclass()
class TimerConfig:
    decorator_type: str
    t: int
    obj_name: str = None
    inner_vars: object = None
    mod: object = None


@dataclass()
class StreamTopic:
    stream: str
    model: str
    group: str = None


