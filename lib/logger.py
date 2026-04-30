#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logger.py
=========
为 rakuten-script 项目提供统一的日志模块。
- 同时输出到控制台和日志文件
- 日志文件按脚本名称+时间自动生成，存放在 logs/ 目录
- 支持实时刷新（每行写入后立即 flush）
- print() 语句无需改动，通过 setup_logger() 自动劫持 stdout/stderr

用法:
    from lib.logger import setup_logger
    setup_logger("rakuten_aff_apply")   # 在 main() 最顶部调用
    # 之后所有 print() 都会同时写入日志文件
"""

import io
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class _TeeWriter(io.TextIOBase):
    """将写入内容同时发送到终端和日志文件的流包装器。"""

    def __init__(self, original_stream, log_file):
        super().__init__()
        self._original = original_stream
        self._log_file = log_file

    # --- io.TextIOBase 必须实现的方法 ---

    def write(self, text: str) -> int:
        if not text:
            return 0
        # 写入终端
        try:
            self._original.write(text)
            self._original.flush()
        except Exception:
            pass
        # 写入日志文件
        try:
            self._log_file.write(text)
            self._log_file.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        try:
            self._log_file.flush()
        except Exception:
            pass

    # --- 兼容属性 ---

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return False

    @property
    def name(self):
        return getattr(self._original, "name", "<tee>")


_log_file_handle = None
_log_file_path: Optional[str] = None


def setup_logger(script_name: str, log_dir: Optional[str] = None) -> str:
    """
    初始化日志系统。劫持 sys.stdout 和 sys.stderr，使所有 print() 同时输出到日志文件。

    Args:
        script_name: 脚本名称（不含扩展名），用于生成日志文件名。
        log_dir: 日志目录路径，默认为项目根目录下的 logs/。

    Returns:
        生成的日志文件绝对路径。
    """
    global _log_file_handle, _log_file_path

    # 确定日志目录
    target_dir = Path(log_dir) if log_dir else _LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # 生成带时间戳的日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"{script_name}_{timestamp}.log"
    log_path = target_dir / log_filename
    _log_file_path = str(log_path)

    # 打开日志文件（追加模式，UTF-8）
    _log_file_handle = open(log_path, "a", encoding="utf-8", errors="replace")

    # 写入日志头
    _log_file_handle.write(f"{'=' * 60}\n")
    _log_file_handle.write(f"  {script_name} 日志\n")
    _log_file_handle.write(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log_file_handle.write(f"  日志文件: {log_path}\n")
    _log_file_handle.write(f"{'=' * 60}\n\n")
    _log_file_handle.flush()

    # 劫持 stdout 和 stderr
    sys.stdout = _TeeWriter(sys.__stdout__, _log_file_handle)
    sys.stderr = _TeeWriter(sys.__stderr__, _log_file_handle)

    print(f"INFO: 日志文件已创建: {log_path}")
    return _log_file_path


def get_log_file_path() -> Optional[str]:
    """返回当前日志文件路径，如果未初始化则返回 None。"""
    return _log_file_path


def close_logger():
    """关闭日志文件并恢复原始 stdout/stderr。"""
    global _log_file_handle

    # 恢复原始流
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

    if _log_file_handle:
        try:
            _log_file_handle.write(f"\n{'=' * 60}\n")
            _log_file_handle.write(f"  日志结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            _log_file_handle.write(f"{'=' * 60}\n")
            _log_file_handle.flush()
            _log_file_handle.close()
        except Exception:
            pass
        _log_file_handle = None
