import subprocess
from pathlib import Path


class WorkspaceContext:
    """保存 Agent 所需的工作区静态信息。"""

    def __init__(self, cwd, repo_root, branch, default_branch, status, recent_commits, project_docs):
        """初始化工作区上下文；参数为路径和 Git/文档信息，返回 None。"""
        self.cwd, self.repo_root = str(cwd), str(repo_root)
        self.branch, self.default_branch = branch, default_branch
        self.status, self.recent_commits, self.project_docs = status, recent_commits, project_docs

    @classmethod
    def build(cls, cwd):
        """收集工作区和 Git 信息；参数为 str 或 Path 目录，返回 WorkspaceContext。"""
        cwd = Path(cwd).resolve()

        def git(args, fallback=""):
            """执行只读 Git 查询；参数为 str 参数列表和默认值，返回命令输出 str。"""
            try:
                result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=5)
                return result.stdout.strip() or fallback
            except (OSError, subprocess.SubprocessError):
                return fallback

        repo_root = Path(git(["rev-parse", "--show-toplevel"], str(cwd))).resolve()
        docs = {}
        for base in (repo_root, cwd):
            for name in ("AGENTS.md", "README.md", "pyproject.toml", "package.json"):
                file_path = base / name
                if file_path.exists():
                    key = str(file_path.relative_to(repo_root))
                    if key not in docs:
                        docs[key] = file_path.read_text(encoding="utf-8", errors="replace")[:1200]
        return cls(cwd, repo_root, git(["branch", "--show-current"], "-"), "main", git(["status", "--short"], "clean") or "clean", git(["log", "--oneline", "-5"]).splitlines(), docs)

    def text(self):
        """格式化工作区上下文；参数为 self，返回可放入 Prompt 的 str。"""
        commits = "\n".join(f"- {item}" for item in self.recent_commits) or "- none"
        docs = "\n".join(f"- {name}\n{text}" for name, text in self.project_docs.items()) or "- none"
        return f"Workspace:\n- cwd: {self.cwd}\n- repo_root: {self.repo_root}\n- branch: {self.branch}\n- status:\n{self.status}\n- recent_commits:\n{commits}\n- project_docs:\n{docs}"
