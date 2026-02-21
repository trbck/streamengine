import numpy as np
import pandas as pd
import time
import asyncio

from app import App, StreamTopic, Message

app = App()

@app.timer(1)
async def timer1():
    await app.send("test_channel", {"test": 10})
    #await app.send("test_channel1", {"test": 10})

@app.agent("test_channel", concurrency=1, group="test")
async def job1(record: Message):
    await app.storage.write('key1', {"key1": "value1"})
    # Latency calculation (if sent and received are available)
    if record.sent is not None and record.received is not None:
        latency_ms = (record.received - record.sent) * 1000
        print(f"[job1] Sent: {record.sent * 1000:.2f} ms | Received: {record.received * 1000:.2f} ms | Latency: {latency_ms:.2f} ms | Message: {record}")
    else:
        print(f"[job1] Message: {record}")

@app.agent("test_channel1", concurrency=1, group="test")
async def job2(record: Message):
    value1 = await app.storage.read('key1')
    # Latency calculation (if sent and received are available)
    if record.sent is not None and record.received is not None:
        latency_ms = (record.received - record.sent) * 1000
        print(f"[job2] Sent: {record.sent * 1000:.2f} ms | Received: {record.received * 1000:.2f} ms | Latency: {latency_ms:.2f} ms | Value: {value1} | Message: {record}")
    else:
        print(f"[job2] Value: {value1} | Message: {record}")

if __name__ == "__main__":
    import sys
    import os
    try:
        app.start()
    except KeyboardInterrupt:
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0) 