import json
from pathlib import Path


class SessionStore:
    """管理工作区内 JSON 会话文件。"""

    def __init__(self, root):
        """初始化会话目录；参数为 str 或 Path 会话根目录，返回 None。"""
        self.root = Path(root)

    def path(self, session_id):
        """生成会话文件路径；参数为 str 会话 ID，返回 Path。"""
        return self.root / f"{session_id}.json"

    def save(self, session):
        """保存会话 JSON；参数为 dict 会话数据，返回保存位置 Path。"""
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path(session["id"])
        target.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def load(self, session_id):
        """读取会话 JSON；参数为 str 会话 ID，返回 dict 会话数据。"""
        return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        """查找最近会话；参数为 self，返回 str 会话 ID 或 None。"""
        files = sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime)
        return files[-1].stem if files else None
