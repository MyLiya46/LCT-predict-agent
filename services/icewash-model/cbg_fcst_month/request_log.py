# -*- coding: utf-8 -*-
"""按请求时间戳落盘运行日志：捕获 print 与 logging 输出。"""
from __future__ import annotations

import contextvars
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

# 当前请求日志会话标识（支持 asyncio 任务与 copy_context 传到工作线程）
_current_log_token: contextvars.ContextVar[Optional[object]] = contextvars.ContextVar(
    "current_log_token", default=None
)


class _TokenLogFilter(logging.Filter):
    """仅放行属于本请求会话的日志记录。"""

    def __init__(self, token: object):
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        return _current_log_token.get() is self.token


class _ThreadAwareTee:
    """进程级 stdout/stderr 代理：按线程将输出 tee 到对应请求日志文件。"""

    def __init__(self, original: TextIO):
        self._original = original
        self._lock = threading.Lock()
        self._thread_files: dict[int, TextIO] = {}

    def register(self, file_obj: TextIO) -> None:
        self._thread_files[threading.get_ident()] = file_obj

    def unregister(self) -> None:
        self._thread_files.pop(threading.get_ident(), None)

    def write(self, data: str) -> int:
        with self._lock:
            try:
                self._original.write(data)
            except Exception:
                pass
            file_obj = self._thread_files.get(threading.get_ident())
            if file_obj is not None:
                try:
                    file_obj.write(data)
                    file_obj.flush()
                except Exception:
                    pass
        return len(data) if isinstance(data, str) else 0

    def flush(self) -> None:
        with self._lock:
            try:
                self._original.flush()
            except Exception:
                pass
            file_obj = self._thread_files.get(threading.get_ident())
            if file_obj is not None:
                try:
                    file_obj.flush()
                except Exception:
                    pass

    def isatty(self) -> bool:
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def __getattr__(self, name: str):
        return getattr(self._original, name)


_stdout_tee: Optional[_ThreadAwareTee] = None
_stderr_tee: Optional[_ThreadAwareTee] = None
_install_lock = threading.Lock()


def _ensure_tee_installed() -> tuple[_ThreadAwareTee, _ThreadAwareTee]:
    global _stdout_tee, _stderr_tee
    with _install_lock:
        if _stdout_tee is None:
            _stdout_tee = _ThreadAwareTee(sys.__stdout__ or sys.stdout)
            sys.stdout = _stdout_tee
        if _stderr_tee is None:
            _stderr_tee = _ThreadAwareTee(sys.__stderr__ or sys.stderr)
            sys.stderr = _stderr_tee
        return _stdout_tee, _stderr_tee


def ensure_log_dir(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def make_request_log_path(log_dir: Path, when: Optional[datetime] = None) -> Path:
    """按请求时间戳生成日志文件路径，例如 20260813_095230_123456.txt。"""
    ensure_log_dir(log_dir)
    ts = (when or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    path = log_dir / f"{ts}.txt"
    if path.exists():
        idx = 1
        while True:
            candidate = log_dir / f"{ts}_{idx}.txt"
            if not candidate.exists():
                return candidate
            idx += 1
    return path


class RequestLogSession:
    """
    单次请求日志会话。

    - start/stop：打开日志文件并挂接 logging.FileHandler（带 token 过滤，避免并发串写）
    - bind/unbind_prints：仅将当前线程的 print/stdout/stderr 写入同一文件
    - 工作线程请用 contextvars.copy_context().run(...) 继承 token
    """

    def __init__(self, log_path: Path, logger_names: Optional[list[str]] = None):
        self.log_path = Path(log_path)
        # 默认只挂 root，子 logger 经 propagate 写入，避免重复
        self.logger_names = logger_names if logger_names is not None else [""]
        self._file: Optional[TextIO] = None
        self._handler: Optional[logging.FileHandler] = None
        self._tee_bound = False
        self._write_lock = threading.Lock()
        self._token = object()
        self._token_reset: Optional[contextvars.Token] = None

    @property
    def token(self) -> object:
        return self._token

    def start(self, header: Optional[str] = None) -> "RequestLogSession":
        ensure_log_dir(self.log_path.parent)
        self._token_reset = _current_log_token.set(self._token)

        self._file = open(self.log_path, "a", encoding="utf-8", buffering=1)
        banner = header or (
            f"===== 请求日志开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
            f"log_file={self.log_path}\n"
        )
        with self._write_lock:
            self._file.write(banner)
            if not banner.endswith("\n"):
                self._file.write("\n")
            self._file.flush()

        self._handler = logging.FileHandler(self.log_path, encoding="utf-8")
        self._handler.setLevel(logging.DEBUG)
        self._handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self._handler.addFilter(_TokenLogFilter(self._token))
        for name in self.logger_names:
            logging.getLogger(name).addHandler(self._handler)
        return self

    def bind_prints(self) -> None:
        if self._file is None:
            raise RuntimeError("RequestLogSession 尚未 start()")
        # 工作线程若未 copy_context，仍保证本线程 logger 可写入
        _current_log_token.set(self._token)
        stdout_tee, stderr_tee = _ensure_tee_installed()
        stdout_tee.register(self._file)
        stderr_tee.register(self._file)
        self._tee_bound = True

    def unbind_prints(self) -> None:
        if not self._tee_bound:
            return
        stdout_tee, stderr_tee = _ensure_tee_installed()
        stdout_tee.unregister()
        stderr_tee.unregister()
        self._tee_bound = False

    def write_line(self, text: str) -> None:
        if self._file is None:
            return
        with self._write_lock:
            self._file.write(text if text.endswith("\n") else text + "\n")
            self._file.flush()

    def stop(self) -> None:
        self.unbind_prints()

        if self._handler is not None:
            for name in self.logger_names:
                logging.getLogger(name).removeHandler(self._handler)
            try:
                self._handler.close()
            except Exception:
                pass
            self._handler = None

        if self._file is not None:
            try:
                with self._write_lock:
                    self._file.write(
                        f"===== 请求日志结束 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
                    )
                    self._file.flush()
                    self._file.close()
            except Exception:
                pass
            self._file = None

        if self._token_reset is not None:
            try:
                _current_log_token.reset(self._token_reset)
            except Exception:
                pass
            self._token_reset = None
