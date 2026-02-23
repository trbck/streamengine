"""
Basic StreamMachine Usage Example

This example demonstrates the core features of StreamMachine:
- Creating an App instance
- Registering agents (message consumers)
- Registering timers (periodic tasks)
- Using shared storage
- Sending and receiving messages

Run with: python basic_usage.py
"""
import asyncio
from streammachine import App, Message


def main():
    # Create the application
    app = App(name="basic_example", to_scan=True)

    # Timer: Sends a message every 2 seconds
    @app.timer(2)
    async def produce_messages():
        """Produce test messages to a stream."""
        await app.send("input_stream", {"value": 42, "source": "timer"})
        print("[Timer] Sent message to input_stream")

    # Agent: Consumes messages from input_stream
    @app.agent("input_stream", concurrency=1, group="processors")
    async def process_input(record: Message):
        """Process incoming messages and store results."""
        print(f"[Agent] Received: {record.message}")

        # Store processed data in shared storage
        await app.storage.write("last_message", record.message)

        # Forward to another stream
        await app.send("output_stream", {
            "original": record.message,
            "processed": True
        })

    # Agent: Consumes processed messages
    @app.agent("output_stream", concurrency=1, group="output_handlers")
    async def handle_output(record: Message):
        """Handle processed messages."""
        print(f"[Output] Final message: {record.message}")

        # Read from shared storage
        last_input = await app.storage.read("last_message")
        print(f"[Output] Last input stored: {last_input}")

        # Calculate latency if timestamps are available
        if record.sent and record.received:
            latency_ms = (record.received - record.sent) * 1000
            print(f"[Output] Latency: {latency_ms:.2f} ms")

    # Start the application
    print("Starting StreamMachine basic example...")
    print("Press Ctrl+C to stop\n")
    try:
        app.start()
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()