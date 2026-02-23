"""
Storage Example

This example demonstrates the shared storage feature for sharing
state between agents and timers.

Run with: python storage_example.py
"""
from streammachine import App, Message


def main():
    app = App(name="storage_example")

    # Counter stored in shared storage
    COUNTER_KEY = "message_count"

    @app.timer(1)
    async def producer():
        """Produce messages and track count."""
        # Read current count
        count = await app.storage.read(COUNTER_KEY, default=0)
        count += 1

        # Store updated count
        await app.storage.write(COUNTER_KEY, count)

        # Send message with count
        await app.send("events", {"count": count, "type": "tick"})
        print(f"[Producer] Sent event #{count}")

    @app.agent("events", concurrency=1, group="consumers")
    async def consumer(record: Message):
        """Process events and show storage usage."""
        # Read shared counter
        count = await app.storage.read(COUNTER_KEY, default=0)

        # Read all keys in storage
        keys = await app.storage.keys()
        print(f"[Consumer] Keys in storage: {keys}")

        print(f"[Consumer] Event: {record.message}, Stored count: {count}")

    @app.timer(10)
    async def status():
        """Periodically show storage status."""
        count = await app.storage.read(COUNTER_KEY, default=0)
        keys = await app.storage.keys()
        print(f"\n=== Status ===")
        print(f"Total messages: {count}")
        print(f"Storage keys: {keys}")
        print(f"==============\n")

    print("Starting storage example...")
    print("Press Ctrl+C to stop\n")
    try:
        app.start()
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()