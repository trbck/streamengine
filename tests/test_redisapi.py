"""
Tests for streammachine.redisapi module.

Note: These tests mock Redis connections to avoid requiring a running Redis server.
For integration tests with real Redis, use the integration test markers.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from streammachine.redisapi import RedisConnection


class TestRedisConnection:
    """Tests for RedisConnection class."""

    def test_connection_creation_default(self):
        """Test creating RedisConnection with defaults."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_redis.return_value = MagicMock()
            conn = RedisConnection()
            assert conn.client is not None

    def test_connection_creation_with_params(self):
        """Test creating RedisConnection with custom parameters."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_redis.return_value = MagicMock()
            conn = RedisConnection(
                host="custom_host",
                port=6380,
                db=1,
                max_connections=20,
            )
            # Verify Redis was called with correct params
            mock_redis.assert_called_once()
            call_kwargs = mock_redis.call_args[1]
            assert call_kwargs['host'] == "custom_host"
            assert call_kwargs['port'] == 6380
            assert call_kwargs['db'] == 1
            assert call_kwargs['max_connections'] == 20

    def test_connection_creation_with_url(self):
        """Test creating RedisConnection with URL."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_redis.from_url = MagicMock(return_value=MagicMock())
            conn = RedisConnection(url="redis://custom:6379/2")
            assert conn.client is not None
            mock_redis.from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_method(self):
        """Test closing connection."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_redis.return_value = mock_client

            conn = RedisConnection()
            await conn.close()
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using RedisConnection as async context manager."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_redis.return_value = mock_client

            async with RedisConnection() as conn:
                assert conn is not None

            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test health check when Redis is healthy."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_client = MagicMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_redis.return_value = mock_client

            conn = RedisConnection()
            result = await conn.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check when Redis is unavailable."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_client = MagicMock()
            mock_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
            mock_redis.return_value = mock_client

            conn = RedisConnection()
            result = await conn.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_pipeline_xadd(self):
        """Test batch adding records with pipeline."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_client = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.xadd = AsyncMock()
            mock_pipeline.execute = AsyncMock(return_value=["id1", "id2"])
            mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
            mock_pipeline.__aexit__ = AsyncMock(return_value=None)
            mock_client.pipeline = MagicMock(return_value=mock_pipeline)
            mock_redis.return_value = mock_client

            conn = RedisConnection()
            records = [{"key": "value1"}, {"key": "value2"}]
            result = await conn.pipeline_xadd("test_topic", records)

            assert result == ["id1", "id2"]

    @pytest.mark.asyncio
    async def test_consumer_method(self):
        """Test creating a consumer."""
        with patch('streammachine.redisapi.coredis.Redis') as mock_redis:
            mock_client = MagicMock()
            mock_redis.return_value = mock_client

            with patch('streammachine.redisapi.GroupConsumer') as mock_group_consumer:
                mock_consumer = MagicMock()
                # GroupConsumer() returns an awaitable that returns the consumer
                # So we need to make the return_value a coroutine
                async def make_consumer(*args, **kwargs):
                    return mock_consumer
                # When GroupConsumer is called, it returns a coroutine
                mock_group_consumer.side_effect = lambda *args, **kwargs: make_consumer(*args, **kwargs)

                conn = RedisConnection()
                consumer = await conn.consumer(
                    channel=["stream1"],
                    consumer="consumer1",
                    group="group1",
                )
                assert consumer is not None