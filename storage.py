import multiprocessing
import asyncio
from collections import defaultdict

class Storage:
    _instance = None  # Singleton instance

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Storage, cls).__new__(cls)
            cls._instance.init_storage()
        return cls._instance

    def init_storage(self):
        """Initialize the storage attributes."""
        self.manager = multiprocessing.Manager()
        self.shared_dict = self.manager.dict()
        self.command_queue = self.manager.Queue()
        
        # Dictionary of locks, one for each key
        self.key_locks = defaultdict(asyncio.Lock)
        
        self.lock_reading = True  # By default, lock during reading

    def handle_commands(self):
        """Listen and handle incoming commands."""
        while True:
            command, args, kwargs = self.command_queue.get()
            if command == "terminate":
                break

    async def start(self):
        """Start listening for commands asynchronously."""
        loop = asyncio.get_event_loop()
        self.command_handler = await loop.run_in_executor(None, self.handle_commands)

    async def terminate(self):
        """Terminate the command handler process."""
        await asyncio.to_thread(self.command_queue.put, ("terminate", [], {}))

    async def write(self, key, value):
        """Asynchronously write a key-value pair to the shared dictionary."""
        async with self.key_locks[key]:
            self.shared_dict[key] = value

    async def read(self, key):
        """Asynchronously read a value from the shared dictionary."""
        # While reading, we don't necessarily need a lock if we're using individual key locks for writing
        # But, if you want to ensure that a read operation is also locked, uncomment the line below
        # async with self.key_locks[key]:
        return self.shared_dict.get(key, None)


