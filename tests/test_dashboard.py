"""
Tests for streammachine.dashboard module.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import time

# Skip all tests if FastAPI is not installed
pytest.importorskip("fastapi")

from streammachine.dashboard import (
    DashboardManager,
    InstanceInfo,
    InstanceMetrics,
    start_dashboard,
    stop_dashboard,
    create_app,
    get_dashboard_html,
    INSTANCES_KEY_PREFIX,
    METRICS_KEY_PREFIX,
    MASTER_KEY,
    LOCK_KEY,
)


class TestDashboardManager:
    """Tests for DashboardManager class."""

    def test_singleton_pattern(self):
        """Test that DashboardManager is a singleton."""
        DashboardManager.reset_instance()
        manager1 = DashboardManager()
        manager2 = DashboardManager()
        assert manager1 is manager2
        DashboardManager.reset_instance()

    def test_reset_instance(self):
        """Test resetting singleton instance."""
        DashboardManager.reset_instance()
        manager1 = DashboardManager()
        DashboardManager.reset_instance()
        manager2 = DashboardManager()
        assert manager1 is not manager2
        DashboardManager.reset_instance()

    def test_is_master_initially_false(self):
        """Test that is_master returns False initially."""
        DashboardManager.reset_instance()
        manager = DashboardManager()
        assert manager.is_master() is False
        DashboardManager.reset_instance()


class TestInstanceInfo:
    """Tests for InstanceInfo dataclass."""

    def test_instance_info_creation(self):
        """Test creating InstanceInfo."""
        info = InstanceInfo(
            instance_id="abc123",
            name="test_app",
            pid=12345,
            host="localhost",
            start_time=time.time(),
        )
        assert info.instance_id == "abc123"
        assert info.name == "test_app"
        assert info.pid == 12345

    def test_instance_info_to_dict(self):
        """Test InstanceInfo to_dict method."""
        info = InstanceInfo(
            instance_id="abc123",
            name="test_app",
            pid=12345,
            host="localhost",
            start_time=1234567890.0,
        )
        result = info.to_dict()
        assert isinstance(result, dict)
        assert result["instance_id"] == "abc123"
        assert result["name"] == "test_app"


class TestInstanceMetrics:
    """Tests for InstanceMetrics dataclass."""

    def test_instance_metrics_creation(self):
        """Test creating InstanceMetrics."""
        metrics = InstanceMetrics(
            instance_id="abc123",
            agents=5,
            timers=2,
            active_tasks=10,
            last_heartbeat=time.time(),
        )
        assert metrics.instance_id == "abc123"
        assert metrics.agents == 5
        assert metrics.timers == 2

    def test_instance_metrics_to_dict(self):
        """Test InstanceMetrics to_dict method."""
        metrics = InstanceMetrics(
            instance_id="abc123",
            agents=5,
            timers=2,
            active_tasks=10,
            last_heartbeat=1234567890.0,
        )
        result = metrics.to_dict()
        assert result["agents"] == 5
        assert result["timers"] == 2


class TestCreateApp:
    """Tests for create_app function."""

    def test_create_app_returns_fastapi(self):
        """Test that create_app returns a FastAPI app."""
        from fastapi import FastAPI
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_routes(self):
        """Test that created app has expected routes."""
        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/" in routes
        assert "/api/health" in routes
        assert "/api/instances" in routes
        assert "/api/agents" in routes
        assert "/api/timers" in routes
        assert "/api/storage" in routes
        assert "/api/streams" in routes


class TestGetDashboardHtml:
    """Tests for get_dashboard_html function."""

    def test_returns_html_string(self):
        """Test that get_dashboard_html returns HTML."""
        html = get_dashboard_html()
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "<html>" in html
        assert "</html>" in html

    def test_html_contains_title(self):
        """Test that HTML contains expected title."""
        html = get_dashboard_html()
        assert "StreamMachine Dashboard" in html

    def test_html_contains_javascript(self):
        """Test that HTML contains JavaScript for auto-refresh."""
        html = get_dashboard_html()
        assert "<script>" in html
        assert "fetchData" in html
        assert "startAutoRefresh" in html


class TestStartStopDashboard:
    """Tests for start_dashboard and stop_dashboard functions."""

    @pytest.mark.asyncio
    async def test_start_dashboard_returns_false_without_redis(self):
        """Test that start_dashboard handles missing Redis gracefully."""
        DashboardManager.reset_instance()

        # Mock the Redis connection to fail
        with patch('streammachine.dashboard.DashboardManager._get_redis') as mock_redis:
            mock_redis.side_effect = Exception("Redis not available")
            result = await start_dashboard("test_id", 8000, "localhost")
            assert result is False

        DashboardManager.reset_instance()

    @pytest.mark.asyncio
    async def test_stop_dashboard_is_safe_when_not_master(self):
        """Test that stop_dashboard is safe when not master."""
        DashboardManager.reset_instance()
        # Should not raise when not master
        await stop_dashboard()
        DashboardManager.reset_instance()


class TestAPIEndpoints:
    """Tests for dashboard API endpoints."""

    @pytest.mark.asyncio
    async def test_get_all_instances_from_storage(self):
        """Test _get_all_instances_from_storage helper."""
        from streammachine.dashboard import _get_all_instances_from_storage

        # Create mock storage
        mock_storage = AsyncMock()
        mock_storage.keys = AsyncMock(return_value=[
            "streammachine:instances:abc123",
            "streammachine:instances:def456",
            "other_key",
        ])
        mock_storage.read = AsyncMock(side_effect=lambda k: {
            "streammachine:instances:abc123": {"instance_id": "abc123", "name": "app1"},
            "streammachine:instances:def456": {"instance_id": "def456", "name": "app2"},
        }.get(k))

        instances = await _get_all_instances_from_storage(mock_storage)
        assert len(instances) == 2

    @pytest.mark.asyncio
    async def test_get_metrics_from_storage(self):
        """Test _get_metrics_from_storage helper."""
        from streammachine.dashboard import _get_metrics_from_storage

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value={
            "instance_id": "abc123",
            "agents": 5,
            "timers": 2,
        })

        metrics = await _get_metrics_from_storage(mock_storage, "abc123")
        assert metrics["instance_id"] == "abc123"
        assert metrics["agents"] == 5


class TestDashboardManagerRedisLock:
    """Tests for Redis-based distributed locking."""

    @pytest.mark.asyncio
    async def test_try_become_master_with_redis_lock(self):
        """Test acquiring master lock via Redis."""
        DashboardManager.reset_instance()

        # Mock Redis client
        mock_redis = MagicMock()
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)
        mock_client.expire = AsyncMock()
        mock_redis.client = mock_client

        manager = DashboardManager()
        manager._redis = mock_redis

        result = await manager.try_become_master(8000, "localhost", "test_id")
        assert result is True
        assert manager.is_master() is True

        DashboardManager.reset_instance()

    @pytest.mark.asyncio
    async def test_try_become_master_fails_when_already_locked(self):
        """Test that becoming master fails when another instance holds lock."""
        DashboardManager.reset_instance()

        # Mock Redis client - SET returns None (lock already held)
        mock_redis = MagicMock()
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=None)  # NX condition fails
        mock_redis.client = mock_client

        manager = DashboardManager()
        manager._redis = mock_redis

        result = await manager.try_become_master(8000, "localhost", "test_id")
        assert result is False
        assert manager.is_master() is False

        DashboardManager.reset_instance()

    @pytest.mark.asyncio
    async def test_release_lock(self):
        """Test releasing master lock."""
        DashboardManager.reset_instance()

        # Mock Redis client
        mock_redis = MagicMock()
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)
        mock_client.delete = AsyncMock()
        mock_redis.client = mock_client

        manager = DashboardManager()
        manager._redis = mock_redis

        # Become master first
        await manager.try_become_master(8000, "localhost", "test_id")
        assert manager.is_master() is True

        # Release lock
        await manager.release_lock()
        assert manager.is_master() is False

        DashboardManager.reset_instance()


class TestAppIntegration:
    """Tests for App integration with dashboard."""

    def test_app_has_instance_id(self):
        """Test that App has instance_id attribute."""
        from streammachine import App
        app = App(name="test_app", to_scan=False)
        assert hasattr(app, '_instance_id')
        assert app._instance_id is not None

    def test_app_has_dashboard_config(self):
        """Test that App config includes dashboard settings."""
        from streammachine import App
        app = App(
            name="test_app",
            to_scan=False,
            dashboard_enabled=True,
            dashboard_port=9000,
            dashboard_host="0.0.0.0",
        )
        assert app.config.dashboard_enabled is True
        assert app.config.dashboard_port == 9000
        assert app.config.dashboard_host == "0.0.0.0"

    def test_app_dashboard_disabled_by_default_is_true(self):
        """Test that dashboard is enabled by default."""
        from streammachine import App
        app = App(to_scan=False)
        # Default should be True based on AppConfig
        assert app.config.dashboard_enabled is True


class TestConfigValidation:
    """Tests for AppConfig validation."""

    def test_dashboard_port_validation(self):
        """Test that invalid dashboard_port raises error."""
        from streammachine.models import AppConfig
        import pytest

        with pytest.raises(ValueError):
            AppConfig(name="test", dashboard_port=0)

        with pytest.raises(ValueError):
            AppConfig(name="test", dashboard_port=70000)

    def test_dashboard_refresh_interval_validation(self):
        """Test that invalid dashboard_refresh_interval raises error."""
        from streammachine.models import AppConfig
        import pytest

        with pytest.raises(ValueError):
            AppConfig(name="test", dashboard_refresh_interval=0)

    def test_valid_dashboard_config(self):
        """Test that valid dashboard config is accepted."""
        from streammachine.models import AppConfig
        config = AppConfig(
            name="test",
            dashboard_enabled=True,
            dashboard_port=8080,
            dashboard_host="localhost",
            dashboard_refresh_interval=10,
        )
        assert config.dashboard_port == 8080
        assert config.dashboard_refresh_interval == 10