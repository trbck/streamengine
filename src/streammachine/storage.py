from __future__ import annotations

import asyncio
import logging
import multiprocessing
import threading
from collections import defaultdict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class Storage:
    """
    Singleton async storage manager using multiprocessing.Manager for shared state.

    Uses asyncio.Lock for per-key write protection. Thread-safe singleton pattern
    ensures only one instance exists across the application.

    Example:
        storage = Storage()
        await storage.write("key", {"data": "value"})
        value = await storage.read("key")
    """

    _instance: Optional[Storage] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> Storage:
        """
        Create or return the singleton instance.

        Uses double-checked locking for thread safety.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super(Storage, cls).__new__(cls)
                    instance._init_storage()
                    cls._instance = instance
                    logger.debug("Storage singleton created")
        return cls._instance

    def _init_storage(self) -> None:
        """Initialize the storage attributes."""
        if self._initialized:
            return

        self.manager = multiprocessing.Manager()
        self.shared_dict: Dict[str, Any] = self.manager.dict()
        self.command_queue = self.manager.Queue()
        # Dictionary of locks, one for each key (write lock only)
        self._key_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = threading.Lock()  # Protect _key_locks access
        self.lock_reading = False  # By default, don't lock during reading
        self._initialized = True
        logger.debug("Storage initialized")

    def _get_lock(self, key: str) -> asyncio.Lock:
        """
        Get or create a lock for the given key.

        Args:
            key: The key to get a lock for

        Returns:
            asyncio.Lock for the key
        """
        with self._locks_lock:
            if key not in self._key_locks:
                self._key_locks[key] = asyncio.Lock()
            return self._key_locks[key]

    def handle_commands(self) -> None:
        """Listen and handle incoming commands (blocking, for background process)."""
        logger.debug("Command handler started")
        while True:
            try:
                command, args, kwargs = self.command_queue.get()
                if command == "terminate":
                    logger.debug("Command handler terminating")
                    break
            except Exception as e:
                logger.error(f"Error in command handler: {e}")

    async def start(self) -> None:
        """Start listening for commands asynchronously (in executor)."""
        loop = asyncio.get_event_loop()
        self.command_handler = await loop.run_in_executor(None, self.handle_commands)

    async def terminate(self) -> None:
        """Terminate the command handler process."""
        await asyncio.to_thread(self.command_queue.put, ("terminate", [], {}))
        logger.debug("Storage termination signal sent")

    async def write(self, key: str, value: Any) -> None:
        """
        Asynchronously write a key-value pair to the shared dictionary.

        Uses per-key locking to prevent concurrent writes to the same key.

        Args:
            key: The key to write
            value: The value to store
        """
        lock = self._get_lock(key)
        async with lock:
            self.shared_dict[key] = value
        logger.debug(f"Wrote value to key '{key}'")

    async def read(self, key: str, default: Any = None) -> Any:
        """
        Asynchronously read a value from the shared dictionary.

        Args:
            key: The key to read
            default: Default value if key doesn't exist

        Returns:
            The stored value or default
        """
        if self.lock_reading:
            lock = self._get_lock(key)
            async with lock:
                return self.shared_dict.get(key, default)
        return self.shared_dict.get(key, default)

    async def delete(self, key: str) -> bool:
        """
        Delete a key from the shared dictionary.

        Args:
            key: The key to delete

        Returns:
            True if key was deleted, False if key didn't exist
        """
        lock = self._get_lock(key)
        async with lock:
            if key in self.shared_dict:
                del self.shared_dict[key]
                logger.debug(f"Deleted key '{key}'")
                return True
            return False

    async def exists(self, key: str) -> bool:
        """
        Check if a key exists in the shared dictionary.

        Args:
            key: The key to check

        Returns:
            True if key exists, False otherwise
        """
        return key in self.shared_dict

    async def keys(self) -> list:
        """
        Get all keys in the shared dictionary.

        Returns:
            List of keys
        """
        return list(self.shared_dict.keys())

    async def clear(self) -> None:
        """Clear all keys from the shared dictionary."""
        self.shared_dict.clear()
        with self._locks_lock:
            self._key_locks.clear()
        logger.debug("Storage cleared")

    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance.

        This is primarily useful for testing.
        Warning: This will lose all stored data.
        """
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.manager.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down manager: {e}")
                cls._instance = None
                cls._initialized = False
                logger.debug("Storage instance reset")


# --- Cythonization candidates ---
# If you have any CPU-bound data processing, mark here for Cythonization.
# Example:
# def heavy_processing(...):
#     ... # Move to .pyx and use nogil for true parallelism