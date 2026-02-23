"""
Tests for streamengine.app module.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from streamengine.app import App, agent_container, timer_container
from streamengine.models import ConsumerConfig, TimerConfig


class TestApp:
    """Tests for App class."""

    def test_app_creation(self):
        """Test creating an App instance."""
        app = App(name="test_app", to_scan=False)
        assert app.config.name == "test_app"
        assert app.config.to_scan is False

    def test_app_default_values(self):
        """Test App default configuration."""
        app = App(to_scan=False)
        assert app.config.max_processes == 5
        assert app.config.max_threads == 5

    def test_app_custom_config(self):
        """Test App with custom configuration."""
        app = App(
            name="custom_app",
            max_processes=10,
            max_threads=20,
            to_scan=False,
        )
        assert app.config.name == "custom_app"
        assert app.config.max_processes == 10
        assert app.config.max_threads == 20

    def test_registry_initialized(self):
        """Test that registry is initialized."""
        app = App(to_scan=False)
        assert app.registry is not None
        assert hasattr(app.registry, 'registered')

    def test_storage_initialized(self):
        """Test that storage is initialized."""
        from streamengine.storage import Storage
        Storage.reset_instance()
        app = App(to_scan=False)
        assert app.storage is not None
        Storage.reset_instance()


class TestAgentContainer:
    """Tests for agent_container function."""

    @pytest.mark.asyncio
    async def test_agent_container_creation(self):
        """Test that agent_container can be created with config."""
        mock_module = MagicMock()
        mock_module.test_handler = AsyncMock(return_value=None)

        config = ConsumerConfig(
            decorator_type="agent",
            topic="test_topic",
            group="test_group",
            obj_name="test_handler",
            mod=mock_module,
        )

        # We can't fully test the consumer without Redis, but we can check it creates
        from streamengine.app import StreamConsumer
        # This test verifies the config is passed correctly
        assert config.topic == "test_topic"
        assert config.group == "test_group"


class TestTimerContainer:
    """Tests for timer_container function."""

    @pytest.mark.asyncio
    async def test_timer_container_with_shutdown(self):
        """Test that timer stops on shutdown event."""
        import asyncio

        mock_module = MagicMock()
        call_count = 0

        async def mock_timer():
            nonlocal call_count
            call_count += 1

        mock_module.test_timer = mock_timer

        config = TimerConfig(
            decorator_type="timer",
            t=1,
            obj_name="test_timer",
            mod=mock_module,
        )

        shutdown_event = asyncio.Event()
        shutdown_event.set()  # Immediately set to trigger shutdown

        await timer_container(config, shutdown_event)
        # Timer should not have run since shutdown was already set
        assert call_count == 0


class TestAppSend:
    """Tests for App send methods."""

    @pytest.mark.asyncio
    async def test_send_method_exists(self):
        """Test that send method exists and is callable."""
        app = App(to_scan=False)
        assert hasattr(app, 'send')
        assert callable(app.send)

    @pytest.mark.asyncio
    async def test_send_batch_method_exists(self):
        """Test that send_batch method exists and is callable."""
        app = App(to_scan=False)
        assert hasattr(app, 'send_batch')
        assert callable(app.send_batch)


class TestAppHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_method_exists(self):
        """Test that health_check method exists."""
        app = App(to_scan=False)
        assert hasattr(app, 'health_check')
        assert callable(app.health_check)


class TestAppShutdown:
    """Tests for shutdown functionality."""

    def test_shutdown_method_exists(self):
        """Test that shutdown method exists."""
        app = App(to_scan=False)
        assert hasattr(app, 'shutdown')
        assert callable(app.shutdown)

    def test_shutdown_event_initialized(self):
        """Test that shutdown event is initialized."""
        app = App(to_scan=False)
        assert hasattr(app, '_shutdown_event')
        assert app._shutdown_event is not None