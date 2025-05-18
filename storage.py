import multiprocessing
import asyncio
from collections import defaultdict
from typing import Any, Optional

class Storage:
    """
    Singleton async storage manager using multiprocessing.Manager for shared state.
    Uses asyncio.Lock for per-key write protection.
    """
    _instance: Optional['Storage'] = None  # Singleton instance

    def __new__(cls) -> 'Storage':
        if cls._instance is None:
            cls._instance = super(Storage, cls).__new__(cls)
            cls._instance.init_storage()
        return cls._instance

    def init_storage(self) -> None:
        """Initialize the storage attributes."""
        self.manager = multiprocessing.Manager()
        self.shared_dict = self.manager.dict()
        self.command_queue = self.manager.Queue()
        # Dictionary of locks, one for each key (write lock only)
        self.key_locks = defaultdict(asyncio.Lock)
        self.lock_reading = True  # By default, lock during reading

    def handle_commands(self) -> None:
        """Listen and handle incoming commands (blocking, for background process)."""
        while True:
            command, args, kwargs = self.command_queue.get()
            if command == "terminate":
                break

    async def start(self) -> None:
        """Start listening for commands asynchronously (in executor)."""
        loop = asyncio.get_event_loop()
        self.command_handler = await loop.run_in_executor(None, self.handle_commands)

    async def terminate(self) -> None:
        """Terminate the command handler process."""
        await asyncio.to_thread(self.command_queue.put, ("terminate", [], {}))

    async def write(self, key: str, value: Any) -> None:
        """Asynchronously write a key-value pair to the shared dictionary (write lock)."""
        async with self.key_locks[key]:
            self.shared_dict[key] = value

    async def read(self, key: str) -> Any:
        """Asynchronously read a value from the shared dictionary (no lock by default)."""
        # If you want to ensure that a read operation is also locked, uncomment below:
        # async with self.key_locks[key]:
        return self.shared_dict.get(key, None)

    # --- Cythonization candidates ---
    # If you have any CPU-bound data processing, mark here for Cythonization.
    # Example:
    # def heavy_processing(...):
    #     ... # Move to .pyx and use nogil for true parallelism


