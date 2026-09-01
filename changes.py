from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path


class ChangeRecord:
    """表示一次可回滚的单文件文本变更。"""

    def __init__(self, path, before, after, operation, timestamp):
        """初始化变更记录；参数为相对路径、前后文本、操作名和时间，返回 None。"""
        self.path = path
        self.before = before
        self.after = after
        self.operation = operation
        self.timestamp = timestamp


def preview_change(root, path, operation, before, after):
    """生成单文件统一 diff；参数为根目录、相对路径、操作名及前后文本，返回 diff str。"""
    relative = str(path)
    old_lines = (before or "").splitlines(keepends=True)
    new_lines = (after or "").splitlines(keepends=True)
    return "".join(unified_diff(old_lines, new_lines, fromfile=f"a/{relative}", tofile=f"b/{relative}")) or "(no changes)"


def _read_current(root, relative):
    """读取目标当前 UTF-8 文本；参数为根目录和相对路径，返回文本或 None。"""
    target = Path(root) / relative
    if not target.exists():
        return None
    if not target.is_file():
        raise ValueError("target is not a file")
    return target.read_text(encoding="utf-8")


def apply_change(root, path, operation, before, after):
    """在内容未变化时应用单文件变更；参数为根目录、路径、操作和前后文本，返回摘要 str。"""
    target = Path(root) / path
    current = _read_current(root, path)
    if current != before:
        raise ValueError(f"change conflict for {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(after or "", encoding="utf-8")
    verb = "wrote" if operation == "write_file" else "patched"
    return f"{verb} {path}"


def rollback_change(root, record):
    """在内容仍等于变更后版本时恢复单文件；参数为根目录和 ChangeRecord，返回摘要 str。"""
    current = _read_current(root, record.path)
    if current != record.after:
        raise ValueError(f"rollback conflict for {record.path}")
    target = Path(root) / record.path
    if record.before is None:
        target.unlink()
        return f"removed {record.path}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(record.before, encoding="utf-8")
    return f"rolled back {record.path}"


def timestamp():
    """生成 UTC 变更时间；参数为无，返回 ISO 8601 str。"""
    return datetime.now(timezone.utc).isoformat()
