import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from context import clip


class AuditLog:
    """管理单个会话的追加式 JSONL 审计日志。"""

    def __init__(self, root):
        """初始化审计文件路径；参数为日志文件 Path 或 str，返回 None。"""
        self.path = Path(root)
        self._lock = threading.Lock()

    def append(self, event, **fields):
        """追加一条审计事件；参数为事件名和结构化字段，返回 None。"""
        item = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.path.stem,
            "event": event,
            **{key: self._sanitize(key, value) for key, value in fields.items()},
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(item, ensure_ascii=False) + "\n")

    def read(self, limit=None):
        """读取审计事件；参数为可选正整数上限，返回 dict 列表。"""
        if not self.path.exists():
            return []
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        return records[-limit:] if limit is not None else records

    def clear(self):
        """清空当前审计文件；参数为 self，返回 None。"""
        if self.path.exists():
            self.path.unlink()

    @staticmethod
    def _sanitize(key, value):
        """裁剪文本并脱敏敏感字段；参数为字段名和值，返回可序列化值。"""
        lowered = key.lower()
        if lowered in {"api_key", "access_token", "auth_token", "secret", "password"}:
            return "[redacted]"
        if isinstance(value, str):
            return clip(value)
        if isinstance(value, dict):
            return {str(item_key): AuditLog._sanitize(str(item_key), item_value) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [AuditLog._sanitize(key, item) for item in value]
        return value
