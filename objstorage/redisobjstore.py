import redis.asyncio as redis
import pickle
import time
import asyncio
import logging

class RedisObjectStorage:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0, log_level=logging.WARNING):
        """
        Initializes the Redis client and logger.
        """
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db)
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=log_level)
        
    async def store_with_pickle(self, key, obj):
        """
        Stores a Python object in Redis using pickle serialization with a lock specific to the key.
        """
        lock = redis.lock.Lock(self.redis_client, f"lock:{key}")
        async with lock:
            start_time = time.time()
            pickled_obj = pickle.dumps(obj)
            await self.redis_client.set(key, pickled_obj)
            end_time = time.time()
            t = (end_time - start_time) * 1000
            self.logger.info(f"Pickle serialization time for {key}: {t} ms")

    async def retrieve_with_pickle(self, key):
        """
        Retrieves a Python object from Redis using pickle deserialization.
        """
        start_time = time.time()
        pickled_obj = await self.redis_client.get(key)
        obj = pickle.loads(pickled_obj) if pickled_obj else None
        end_time = time.time()
        t = (end_time - start_time) * 1000
        self.logger.info(f"Pickle read time for {key}: {t} ms")
        return obj

    async def list_keys(self, pattern="*"):
        """
        Lists all keys in Redis that match the given pattern.
        """
        keys = await self.redis_client.keys(pattern)
        keys = [key.decode('utf-8') for key in keys]  # Decode keys from bytes to strings
        self.logger.info(f"Keys matching pattern '{pattern}': {keys}")
        return keys

    async def delete_keys(self, pattern):
        """
        Deletes all keys in Redis that match the given pattern.
        """
        keys = await self.redis_client.keys(pattern)
        if keys:
            await self.redis_client.delete(*keys)
            self.logger.info(f"Deleted keys matching pattern '{pattern}': {[key.decode('utf-8') for key in keys]}")
        else:
            self.logger.info(f"No keys matching pattern '{pattern}' found to delete.")

    async def close(self):
        """
        Closes the Redis client connection.
        """
        await self.redis_client.close()