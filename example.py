import numpy as np
import pandas as pd
import time
import asyncio

from app import App, StreamTopic, Message


app = App()

@app.timer(1)
async def timer1():
    await app.send("test_channel", {"test": 10})
    await app.send("test_channel1", {"test": 10})


@app.agent("test_channel", concurrency=1, group="test")
async def job1(record):
    await app.storage.write('key1', {"key1": "value1"})
    #app.storage.awake(key) - return dataclass but keep look as long as processing is done here and then write back
    # and close
    # provide other option to just awake and read without lock
    # 

    # Asynchronously read with lock
    #value1 = await app.storage.read('key1')
    #print(value1)


@app.agent("test_channel1", concurrency=1, group="test")
async def job2(record):

    value1 = await app.storage.read('key1')
    print(value1)
    print(record)



if __name__ == "__main__":
    import sys
    import os
    try:
        app.start()
    except KeyboardInterrupt:
        try:
            #asyncio.run(app.shutdown())
            sys.exit(0)
        except SystemExit:
            os._exit(0)

#add dataclasses picked to redis to enable app wide storage of data across agents

# add send_and_wait_result([channels], message)
#then connect to the result channel and count receipts via while loop as expected and close all 
# this overall ensures an ordered processing of messages!!

