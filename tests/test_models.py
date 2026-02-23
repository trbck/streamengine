"""
Tests for streamengine.models module.
"""
import pytest
import pandas as pd
from dataclasses import asdict

from streamengine.models import (
    Message,
    AppConfig,
    ConsumerConfig,
    TimerConfig,
    StreamTopic,
    dataclass_list_to_dataframe,
    dataframe_to_dataclass_list,
)


class TestMessage:
    """Tests for Message dataclass."""

    def test_message_creation(self):
        """Test basic message creation."""
        msg = Message(
            topic="test_topic",
            key="test_key",
            sent=1234567890.0,
            received=1234567890.5,
            data={(b'key', b'value')},
        )
        assert msg.topic == "test_topic"
        assert msg.key == "test_key"
        assert msg.sent == 1234567890.0
        assert msg.received == 1234567890.5

    def test_message_message_property(self, sample_message_data):
        """Test message property decodes bytes to strings."""
        msg = Message(data=sample_message_data)
        decoded = msg.message
        assert decoded['key1'] == 'value1'
        assert decoded['key2'] == 'value2'

    def test_message_timer_property(self):
        """Test timer property calculates latency."""
        msg = Message(
            topic="test",
            sent=100.0,
            received=100.5,
        )
        assert "500.00 ms" in msg.timer

    def test_message_timer_property_no_times(self):
        """Test timer property returns empty string when times are missing."""
        msg = Message(topic="test")
        assert msg.timer == ""

    def test_message_to_dict(self):
        """Test to_dict method."""
        msg = Message(topic="test", key="key1")
        d = msg.to_dict()
        assert d['topic'] == "test"
        assert d['key'] == "key1"


class TestAppConfig:
    """Tests for AppConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AppConfig()
        assert config.name == ""
        assert config.to_scan is True
        assert config.max_processes == 5
        assert config.max_threads == 5

    def test_custom_values(self):
        """Test custom configuration values."""
        config = AppConfig(
            name="test_app",
            max_processes=10,
            debug=True,
        )
        assert config.name == "test_app"
        assert config.max_processes == 10
        assert config.debug is True

    def test_validation_max_processes(self):
        """Test validation for max_processes."""
        with pytest.raises(ValueError, match="max_processes must be >= 1"):
            AppConfig(max_processes=0)

    def test_validation_max_threads(self):
        """Test validation for max_threads."""
        with pytest.raises(ValueError, match="max_threads must be >= 1"):
            AppConfig(max_threads=0)

    def test_validation_webserver_port(self):
        """Test validation for webserver_port."""
        with pytest.raises(ValueError, match="webserver_port must be between"):
            AppConfig(webserver_port=0)
        with pytest.raises(ValueError, match="webserver_port must be between"):
            AppConfig(webserver_port=70000)


class TestConsumerConfig:
    """Tests for ConsumerConfig dataclass."""

    def test_default_values(self):
        """Test default consumer configuration."""
        config = ConsumerConfig(
            decorator_type="agent",
            topic="test_topic",
        )
        assert config.group == "eventengine"  # DEFAULT_CONSUMER_GROUP
        assert config.concurrency == 1
        assert config.max_retries == 3

    def test_validation_concurrency(self):
        """Test validation for concurrency."""
        with pytest.raises(ValueError, match="concurrency must be >= 1"):
            ConsumerConfig(decorator_type="agent", topic="test", concurrency=0)

    def test_validation_max_retries(self):
        """Test validation for max_retries."""
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            ConsumerConfig(decorator_type="agent", topic="test", max_retries=-1)


class TestTimerConfig:
    """Tests for TimerConfig dataclass."""

    def test_valid_timer(self):
        """Test valid timer configuration."""
        config = TimerConfig(decorator_type="timer", t=10)
        assert config.t == 10

    def test_validation_negative_time(self):
        """Test validation for negative time."""
        with pytest.raises(ValueError, match="timer interval must be >= 0"):
            TimerConfig(decorator_type="timer", t=-1)


class TestStreamTopic:
    """Tests for StreamTopic dataclass."""

    def test_stream_topic_creation(self):
        """Test stream topic creation."""
        topic = StreamTopic(stream="test_stream", model="TestModel")
        assert topic.stream == "test_stream"
        assert topic.model == "TestModel"
        assert topic.group is None

    def test_stream_topic_with_group(self):
        """Test stream topic with group."""
        topic = StreamTopic(stream="test", model="Model", group="my_group")
        assert topic.group == "my_group"


class TestDataclassConversions:
    """Tests for dataclass conversion utilities."""

    def test_dataclass_list_to_dataframe(self):
        """Test converting list of dataclasses to DataFrame."""
        messages = [
            Message(topic="topic1", key="key1"),
            Message(topic="topic2", key="key2"),
        ]
        df = dataclass_list_to_dataframe(messages)
        assert len(df) == 2
        assert 'topic' in df.columns
        assert 'key' in df.columns

    def test_dataclass_list_to_dataframe_empty(self):
        """Test converting empty list returns empty DataFrame."""
        df = dataclass_list_to_dataframe([])
        assert df.empty

    def test_dataclass_list_to_dataframe_non_dataclass(self):
        """Test error when not dataclass."""
        with pytest.raises(ValueError):
            dataclass_list_to_dataframe([{"a": 1}])

    def test_dataframe_to_dataclass_list(self):
        """Test converting DataFrame to list of dataclasses."""
        # ConsumerConfig has many fields, need to include all for the conversion
        df = pd.DataFrame([
            {
                "decorator_type": "agent",
                "topic": "test1",
                "group": "group1",
                "concurrency": 1,
                "processes": None,
                "max_retries": 3,
                "retry_delay_ms": 100,
                "obj_name": None,
                "inner_vars": None,
                "mod": None,
            },
            {
                "decorator_type": "agent",
                "topic": "test2",
                "group": "group1",
                "concurrency": 2,
                "processes": None,
                "max_retries": 3,
                "retry_delay_ms": 100,
                "obj_name": None,
                "inner_vars": None,
                "mod": None,
            },
        ])
        configs = dataframe_to_dataclass_list(df, ConsumerConfig)
        assert len(configs) == 2
        assert all(isinstance(c, ConsumerConfig) for c in configs)
        assert configs[0].topic == "test1"
        assert configs[1].concurrency == 2

    def test_dataframe_to_dataclass_list_empty(self):
        """Test converting empty DataFrame returns empty list."""
        df = pd.DataFrame()
        result = dataframe_to_dataclass_list(df, ConsumerConfig)
        assert result == []

    def test_dataframe_to_dataclass_list_missing_fields(self):
        """Test error when DataFrame missing required fields."""
        df = pd.DataFrame([{"topic": "test"}])  # Missing decorator_type
        with pytest.raises(ValueError, match="missing required fields"):
            dataframe_to_dataclass_list(df, ConsumerConfig)

    def test_dataframe_to_dataclass_list_extra_fields_warning(self, caplog):
        """Test warning when DataFrame has extra fields."""
        import logging
        caplog.set_level(logging.WARNING)
        df = pd.DataFrame([
            {
                "decorator_type": "agent",
                "topic": "test",
                "group": "group1",
                "concurrency": 1,
                "processes": None,
                "max_retries": 3,
                "retry_delay_ms": 100,
                "obj_name": None,
                "inner_vars": None,
                "mod": None,
                "extra_field": "ignored",  # This should trigger warning
            }
        ])
        configs = dataframe_to_dataclass_list(df, ConsumerConfig)
        assert len(configs) == 1
        assert "extra fields" in caplog.text