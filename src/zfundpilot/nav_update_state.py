"""净值更新共享状态。

api.py 和 scheduler.py 共享此状态，避免循环导入，
确保两路净值更新互斥（手动触发 vs 定时任务）。
"""

from __future__ import annotations

import threading
from typing import Any

nav_update_state: dict[str, Any] = {
    "running": False,
    "total": 0,
    "done": 0,
    "current": "",
    "results": [],
    "error": "",
}

nav_update_lock = threading.Lock()
