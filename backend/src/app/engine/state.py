"""引擎状态枚举（T16 / tech_design §3.4 状态机）。

引擎级 agent_process.state:
  starting → planning → executing ⇄ retrying ⇄ degrading → done | interrupted
"""
from __future__ import annotations

from enum import StrEnum


class EngineState(StrEnum):
    STARTING = "starting"
    PLANNING = "planning"
    EXECUTING = "executing"
    RETRYING = "retrying"
    DEGRADING = "degrading"
    DONE = "done"
    INTERRUPTED = "interrupted"


class MessageStatus(StrEnum):
    SENT = "sent"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"