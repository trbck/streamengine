"""
StreamMachine Dashboard Module

FastAPI dashboard for monitoring StreamMachine tasks across multiple
running App instances. Uses Redis-based distributed locking for singleton
dashboard pattern.

Why Redis lock for singleton?
    - Works across containers, processes, and machines
    - Automatic cleanup via TTL if process crashes
    - Platform-independent (unlike file locks)

Architecture:
    - DashboardManager: Singleton pattern with Redis distributed lock
    - Each App instance registers itself in Storage with heartbeat
    - Dashboard aggregates metrics from all registered instances
    - First started file becomes dashboard master
    - Subsequent files detect existing dashboard and skip startup

Example:
    # In agent_file_a.py
    app = App(name="agent_a", dashboard_enabled=True)
    app.start()  # Dashboard starts on port 8000 (becomes master)

    # In agent_file_b.py
    app = App(name="agent_b", dashboard_enabled=True)
    app.start()  # Dashboard already running, skips startup
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# FastAPI/uvicorn imports (optional dependency)
try:
    from fastapi import FastAPI, Response
    from fastapi.responses import HTMLResponse
    import uvicorn
    _HAS_FASTAPI = True
except ImportError:
    FastAPI = None
    Response = None
    HTMLResponse = None
    uvicorn = None
    _HAS_FASTAPI = False


# Redis key prefixes for dashboard
INSTANCES_KEY_PREFIX = "streammachine:instances:"
METRICS_KEY_PREFIX = "streammachine:metrics:"
MASTER_KEY = "streammachine:dashboard:master"
LOCK_KEY = "streammachine:dashboard:lock"
HEARTBEAT_KEY = "streammachine:dashboard:heartbeat"

# Lock TTL in seconds
LOCK_TTL = 30
HEARTBEAT_INTERVAL = 10


@dataclass
class InstanceInfo:
    """Information about a registered App instance."""
    instance_id: str
    name: str
    pid: int
    host: str
    start_time: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InstanceMetrics:
    """Metrics for a registered App instance."""
    instance_id: str
    agents: int
    timers: int
    active_tasks: int
    last_heartbeat: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DashboardManager:
    """
    Singleton manager for dashboard lifecycle using Redis distributed lock.

    Uses Redis SETNX (SET if Not eXists) for atomic lock acquisition, ensuring
    only one dashboard instance runs across multiple processes/machines.

    Thread Safety:
        - Uses threading.Lock for in-process thread safety
        - Uses Redis SETNX for cross-process/machine coordination
        - Heartbeat task auto-renews the lock

    Attributes:
        _instance: Singleton instance
        _lock: Thread lock for singleton pattern
        _master_info: Info about current master (if this instance is master)
        _server_task: uvicorn server task
        _heartbeat_task: Task for renewing lock and heartbeat
    """

    _instance: Optional[DashboardManager] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> DashboardManager:
        """Create or return singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        """Initialize the dashboard manager."""
        if self._initialized:
            return

        self._is_master = False
        self._master_info: Optional[Dict[str, Any]] = None
        self._server_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._app_instance_id: Optional[str] = None
        self._redis = None
        self._port: int = 8000
        self._host: str = "localhost"
        self._initialized = True
        logger.debug("DashboardManager initialized")

    async def _get_redis(self):
        """Get Redis connection lazily."""
        if self._redis is None:
            from .redisapi import RedisConnection
            self._redis = RedisConnection()
            await self._redis._ensure_pool()
        return self._redis

    async def try_become_master(self, port: int, host: str, app_instance_id: str) -> bool:
        """
        Atomically acquire dashboard master lock via Redis SETNX.

        Args:
            port: Port for the dashboard server
            host: Host for the dashboard server
            app_instance_id: ID of the App instance trying to become master

        Returns:
            True if this instance became master, False if another instance
            already holds the lock
        """
        try:
            redis = await self._get_redis()
            client = redis.client

            # Try to acquire lock with TTL
            # SET key value NX EX ttl
            lock_value = f"{app_instance_id}:{os.getpid()}:{time.time()}"

            acquired = await client.set(
                LOCK_KEY,
                lock_value,
                nx=True,  # Only set if not exists
                ex=LOCK_TTL  # Expire after LOCK_TTL seconds
            )

            if acquired:
                self._is_master = True
                self._app_instance_id = app_instance_id
                self._port = port
                self._host = host
                self._master_info = {
                    "instance_id": app_instance_id,
                    "port": port,
                    "host": host,
                    "started_at": time.time(),
                    "pid": os.getpid()
                }

                # Store master info in Redis for other instances to query
                await client.set(MASTER_KEY, str(self._master_info))

                logger.info(f"DashboardManager became master on {host}:{port}")
                return True
            else:
                logger.info("Dashboard already running, skipping startup")
                return False

        except Exception as e:
            logger.error(f"Failed to acquire dashboard lock: {e}")
            return False

    async def release_lock(self) -> None:
        """Release the master lock and clean up."""
        if not self._is_master:
            return

        try:
            redis = await self._get_redis()
            client = redis.client

            # Delete lock and master info
            await client.delete(LOCK_KEY)
            await client.delete(MASTER_KEY)
            logger.info("Released dashboard lock")
        except Exception as e:
            logger.warning(f"Error releasing dashboard lock: {e}")
        finally:
            self._is_master = False
            self._master_info = None

    async def _heartbeat_loop(self) -> None:
        """Renew lock TTL and update heartbeat periodically."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if self._is_master:
                    # Renew lock TTL
                    redis = await self._get_redis()
                    client = redis.client

                    await client.expire(LOCK_KEY, LOCK_TTL)

                    # Update heartbeat
                    await client.set(
                        HEARTBEAT_KEY,
                        str({"instance_id": self._app_instance_id, "time": time.time()}),
                        ex=LOCK_TTL * 2
                    )

                    logger.debug("Dashboard heartbeat renewed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in dashboard heartbeat: {e}")

    def is_master(self) -> bool:
        """Check if this instance is the dashboard master."""
        return self._is_master

    def get_master_info(self) -> Optional[Dict[str, Any]]:
        """Get info about the current master."""
        return self._master_info

    async def start_server(self) -> None:
        """Start FastAPI server in background."""
        if not self._is_master:
            return

        if not _HAS_FASTAPI:
            logger.warning("FastAPI not installed, dashboard disabled")
            return

        # Create FastAPI app
        app = create_app()

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start uvicorn server
        config = uvicorn.Config(
            app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False
        )
        server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(server.serve())
        logger.info(f"Dashboard started on http://{self._host}:{self._port}")

    async def stop_server(self) -> None:
        """Graceful shutdown and cleanup."""
        self._shutdown_event.set()

        # Cancel heartbeat task
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Release lock
        await self.release_lock()

        logger.info("Dashboard stopped")

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None


def create_app() -> 'FastAPI':
    """Create FastAPI application with dashboard routes."""
    app = FastAPI(
        title="StreamMachine Dashboard",
        description="Monitor StreamMachine tasks across multiple instances",
        version="0.1.0"
    )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_ui():
        """HTML dashboard UI."""
        return get_dashboard_html()

    @app.get("/api/health")
    async def health():
        """Aggregated health from all instances."""
        return await get_aggregated_health()

    @app.get("/api/instances")
    async def instances():
        """List all registered App instances."""
        return await get_all_instances()

    @app.get("/api/instance/{instance_id}")
    async def instance_detail(instance_id: str):
        """Details for specific instance."""
        return await get_instance_detail(instance_id)

    @app.get("/api/agents")
    async def agents():
        """All registered agents across instances."""
        return await get_all_agents()

    @app.get("/api/timers")
    async def timers():
        """All registered timers across instances."""
        return await get_all_timers()

    @app.get("/api/storage")
    async def storage():
        """Storage contents viewer."""
        return await get_storage_contents()

    @app.get("/api/streams")
    async def streams():
        """Redis stream information."""
        return await get_stream_info()

    return app


# API endpoint implementations

async def get_aggregated_health() -> Dict[str, Any]:
    """Get aggregated health from all registered instances."""
    from .storage import Storage

    storage = Storage()
    instances = await _get_all_instances_from_storage(storage)

    total_agents = 0
    total_timers = 0
    total_tasks = 0
    healthy_count = 0
    now = time.time()

    instance_health = []

    for inst in instances:
        metrics = await _get_metrics_from_storage(storage, inst["instance_id"])

        # Check if heartbeat is recent (within 30 seconds)
        is_healthy = (
            metrics and
            (now - metrics.get("last_heartbeat", 0)) < 30
        )

        if is_healthy:
            healthy_count += 1

        total_agents += metrics.get("agents", 0) if metrics else 0
        total_timers += metrics.get("timers", 0) if metrics else 0
        total_tasks += metrics.get("active_tasks", 0) if metrics else 0

        instance_health.append({
            "instance_id": inst["instance_id"],
            "name": inst["name"],
            "healthy": is_healthy,
            "metrics": metrics
        })

    return {
        "status": "healthy" if healthy_count == len(instances) else "degraded",
        "total_instances": len(instances),
        "healthy_instances": healthy_count,
        "total_agents": total_agents,
        "total_timers": total_timers,
        "total_active_tasks": total_tasks,
        "instances": instance_health
    }


async def get_all_instances() -> List[Dict[str, Any]]:
    """List all registered App instances."""
    from .storage import Storage

    storage = Storage()
    instances = await _get_all_instances_from_storage(storage)

    result = []
    now = time.time()

    for inst in instances:
        metrics = await _get_metrics_from_storage(storage, inst["instance_id"])
        is_active = (
            metrics and
            (now - metrics.get("last_heartbeat", 0)) < 30
        )

        result.append({
            **inst,
            "metrics": metrics,
            "active": is_active
        })

    return result


async def get_instance_detail(instance_id: str) -> Dict[str, Any]:
    """Get details for a specific instance."""
    from .storage import Storage

    storage = Storage()
    instance_key = f"{INSTANCES_KEY_PREFIX}{instance_id}"
    instance_data = await storage.read(instance_key)

    if not instance_data:
        return {"error": "Instance not found", "instance_id": instance_id}

    metrics = await _get_metrics_from_storage(storage, instance_id)

    return {
        "instance": instance_data,
        "metrics": metrics
    }


async def get_all_agents() -> List[Dict[str, Any]]:
    """Get all registered agents across instances."""
    from .storage import Storage

    storage = Storage()
    instances = await _get_all_instances_from_storage(storage)

    agents = []
    for inst in instances:
        metrics = await _get_metrics_from_storage(storage, inst["instance_id"])
        if metrics and "agents_detail" in metrics:
            for agent in metrics.get("agents_detail", []):
                agents.append({
                    **agent,
                    "instance_id": inst["instance_id"],
                    "instance_name": inst["name"]
                })

    return agents


async def get_all_timers() -> List[Dict[str, Any]]:
    """Get all registered timers across instances."""
    from .storage import Storage

    storage = Storage()
    instances = await _get_all_instances_from_storage(storage)

    timers = []
    for inst in instances:
        metrics = await _get_metrics_from_storage(storage, inst["instance_id"])
        if metrics and "timers_detail" in metrics:
            for timer in metrics.get("timers_detail", []):
                timers.append({
                    **timer,
                    "instance_id": inst["instance_id"],
                    "instance_name": inst["name"]
                })

    return timers


async def get_storage_contents() -> Dict[str, Any]:
    """Get storage contents (keys only for safety)."""
    from .storage import Storage

    storage = Storage()
    keys = await storage.keys()

    # Filter to dashboard-related keys only
    dashboard_keys = [k for k in keys if k.startswith("streammachine:")]

    result = {}
    for key in dashboard_keys[:100]:  # Limit to 100 keys
        try:
            value = await storage.read(key)
            result[key] = value
        except Exception as e:
            result[key] = f"Error reading: {e}"

    return {
        "total_keys": len(keys),
        "dashboard_keys": len(dashboard_keys),
        "contents": result
    }


async def get_stream_info() -> List[Dict[str, Any]]:
    """Get Redis stream information."""
    from .redisapi import RedisConnection

    try:
        redis = RedisConnection()
        await redis._ensure_pool()
        client = redis.client

        # Get all stream keys
        # Note: This requires SCAN which coredis supports
        streams = []

        # Try to get stream info from storage if available
        from .storage import Storage
        storage = Storage()
        instances = await _get_all_instances_from_storage(storage)

        for inst in instances:
            metrics = await _get_metrics_from_storage(storage, inst["instance_id"])
            if metrics and "streams" in metrics:
                for stream in metrics.get("streams", []):
                    streams.append({
                        "name": stream,
                        "instance_id": inst["instance_id"],
                        "instance_name": inst["name"]
                    })

        return streams
    except Exception as e:
        logger.error(f"Error getting stream info: {e}")
        return []


# Helper functions

async def _get_all_instances_from_storage(storage) -> List[Dict[str, Any]]:
    """Get all registered instances from storage."""
    keys = await storage.keys()
    instance_keys = [k for k in keys if k.startswith(INSTANCES_KEY_PREFIX)]

    instances = []
    for key in instance_keys:
        try:
            data = await storage.read(key)
            if data:
                instances.append(data)
        except Exception as e:
            logger.warning(f"Error reading instance {key}: {e}")

    return instances


async def _get_metrics_from_storage(storage, instance_id: str) -> Optional[Dict[str, Any]]:
    """Get metrics for an instance from storage."""
    metrics_key = f"{METRICS_KEY_PREFIX}{instance_id}"
    return await storage.read(metrics_key)


def get_dashboard_html() -> str:
    """Generate HTML dashboard UI."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>StreamMachine Dashboard</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }
        h1 { color: #333; margin-bottom: 20px; }
        h2 { color: #555; margin-top: 30px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }
        .stat {
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #333;
        }
        .stat-label {
            font-size: 0.85em;
            color: #666;
            margin-top: 5px;
        }
        .status-healthy { color: #28a745; }
        .status-degraded { color: #ffc107; }
        .status-error { color: #dc3545; }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #eee;
        }
        th { background: #f8f9fa; font-weight: 600; }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 500;
        }
        .badge-active { background: #d4edda; color: #155724; }
        .badge-inactive { background: #f8d7da; color: #721c24; }
        .refresh-info {
            color: #666;
            font-size: 0.85em;
            margin-bottom: 15px;
        }
        #last-refresh { font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>StreamMachine Dashboard</h1>
        <div class="refresh-info">Last refresh: <span id="last-refresh">-</span></div>

        <div class="card">
            <h2 style="margin-top:0">Overview</h2>
            <div class="stat-grid">
                <div class="stat">
                    <div class="stat-value" id="total-instances">-</div>
                    <div class="stat-label">Instances</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="total-agents">-</div>
                    <div class="stat-label">Agents</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="total-timers">-</div>
                    <div class="stat-label">Timers</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="total-tasks">-</div>
                    <div class="stat-label">Active Tasks</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2 style="margin-top:0">Instances</h2>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Instance ID</th>
                        <th>PID</th>
                        <th>Status</th>
                        <th>Agents</th>
                        <th>Timers</th>
                        <th>Last Heartbeat</th>
                    </tr>
                </thead>
                <tbody id="instances-table">
                    <tr><td colspan="7">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2 style="margin-top:0">Agents</h2>
            <table>
                <thead>
                    <tr>
                        <th>Topic</th>
                        <th>Group</th>
                        <th>Instance</th>
                        <th>Concurrency</th>
                    </tr>
                </thead>
                <tbody id="agents-table">
                    <tr><td colspan="4">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2 style="margin-top:0">Timers</h2>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Interval</th>
                        <th>Instance</th>
                    </tr>
                </thead>
                <tbody id="timers-table">
                    <tr><td colspan="3">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let refreshInterval;

        async function fetchData() {
            try {
                const [healthRes, instancesRes, agentsRes, timersRes] = await Promise.all([
                    fetch('/api/health'),
                    fetch('/api/instances'),
                    fetch('/api/agents'),
                    fetch('/api/timers')
                ]);

                const health = await healthRes.json();
                const instances = await instancesRes.json();
                const agents = await agentsRes.json();
                const timers = await timersRes.json();

                // Update overview stats
                document.getElementById('total-instances').textContent = health.total_instances;
                document.getElementById('total-agents').textContent = health.total_agents;
                document.getElementById('total-timers').textContent = health.total_timers;
                document.getElementById('total-tasks').textContent = health.total_active_tasks;

                // Update instances table
                const instancesHtml = instances.map(i => {
                    const status = i.active ? 'active' : 'inactive';
                    const statusClass = i.active ? 'badge-active' : 'badge-inactive';
                    const heartbeatAge = i.metrics ?
                        Math.round((Date.now() / 1000) - i.metrics.last_heartbeat) + 's ago' :
                        'N/A';
                    return `<tr>
                        <td>${i.name}</td>
                        <td><code>${i.instance_id}</code></td>
                        <td>${i.pid}</td>
                        <td><span class="badge ${statusClass}">${status}</span></td>
                        <td>${i.metrics?.agents || 0}</td>
                        <td>${i.metrics?.timers || 0}</td>
                        <td>${heartbeatAge}</td>
                    </tr>`;
                }).join('');
                document.getElementById('instances-table').innerHTML = instancesHtml || '<tr><td colspan="7">No instances</td></tr>';

                // Update agents table
                const agentsHtml = agents.map(a => `<tr>
                    <td><code>${a.topic || '-'}</code></td>
                    <td>${a.group || '-'}</td>
                    <td>${a.instance_name}</td>
                    <td>${a.concurrency || 1}</td>
                </tr>`).join('');
                document.getElementById('agents-table').innerHTML = agentsHtml || '<tr><td colspan="4">No agents</td></tr>';

                // Update timers table
                const timersHtml = timers.map(t => `<tr>
                    <td>${t.name || '-'}</td>
                    <td>${t.interval || '-'}s</td>
                    <td>${t.instance_name}</td>
                </tr>`).join('');
                document.getElementById('timers-table').innerHTML = timersHtml || '<tr><td colspan="3">No timers</td></tr>';

                // Update last refresh
                document.getElementById('last-refresh').textContent = new Date().toLocaleTimeString();
            } catch (error) {
                console.error('Error fetching data:', error);
            }
        }

        function startAutoRefresh(intervalSec) {
            if (refreshInterval) clearInterval(refreshInterval);
            refreshInterval = setInterval(fetchData, intervalSec * 1000);
        }

        // Initial fetch and start auto-refresh
        fetchData();
        // Default 5 second refresh, can be configured
        startAutoRefresh(5);
    </script>
</body>
</html>
"""


async def start_dashboard(app_instance_id: str, port: int = 8000, host: str = "localhost") -> bool:
    """
    Start dashboard if not already running.

    Args:
        app_instance_id: Unique ID of the App instance
        port: Port for the dashboard server
        host: Host for the dashboard server

    Returns:
        True if this instance started the dashboard, False if already running
    """
    if not _HAS_FASTAPI:
        logger.warning("FastAPI not installed, dashboard disabled. Install with: pip install fastapi uvicorn")
        return False

    manager = DashboardManager()

    # Try to become master
    became_master = await manager.try_become_master(port, host, app_instance_id)

    if became_master:
        await manager.start_server()
        return True

    return False


async def stop_dashboard() -> None:
    """Stop dashboard if this instance is master."""
    if not _HAS_FASTAPI:
        return

    manager = DashboardManager()
    await manager.stop_server()


# Public API
__all__ = [
    "DashboardManager",
    "InstanceInfo",
    "InstanceMetrics",
    "start_dashboard",
    "stop_dashboard",
    "create_app",
    "get_dashboard_html",
]