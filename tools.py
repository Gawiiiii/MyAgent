import re
import subprocess
from pathlib import Path


def path(root, raw_path):
    """解析工作区内路径；参数为 Path 根目录和 str 相对路径，返回已解析 Path。"""
    workspace = Path(root).resolve()
    candidate = (workspace / raw_path).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ValueError("path escapes workspace")
    return candidate


def list_files(root, args):
    """列出工作区一级内容；参数为 Path 根目录和 dict 参数，返回 str 文件清单。"""
    entries = []
    for item in sorted(Path(root).iterdir(), key=lambda item: item.name):
        entries.append(item.name + ("/" if item.is_dir() else ""))
    return "\n".join(entries) or "(empty workspace)"


def read_file(root, args):
    """读取 UTF-8 文件行；参数为 Path 根目录和含 path/start/end 的 dict，返回带行号 str。"""
    file_path = path(root, args["path"])
    if not file_path.is_file():
        raise ValueError(f"not a file: {args['path']}")
    lines = file_path.read_text(encoding="utf-8").splitlines()
    start, end = int(args.get("start", 1)), int(args.get("end", len(lines)))
    if start < 1 or end < start:
        raise ValueError("line range is invalid")
    return "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, min(end, len(lines)) + 1))


def search(root, args):
    """递归搜索文本模式；参数为 Path 根目录和含非空 pattern 的 dict，返回匹配行 str。"""
    pattern = args["pattern"]
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must not be empty")
    try:
        matcher = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid pattern: {exc}") from exc
    results = []
    workspace = Path(root)
    for file_path in sorted(item for item in workspace.rglob("*") if item.is_file() and ".git" not in item.parts):
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        relative = file_path.relative_to(workspace)
        results.extend(f"{relative}:{number}: {line}" for number, line in enumerate(lines, 1) if matcher.search(line))
    return "\n".join(results) or "(no matches)"


def write_file(root, args):
    """创建或覆盖文件；参数为 Path 根目录和含 path/content 的 dict，返回 str 操作结果。"""
    file_path = path(root, args["path"])
    if file_path.exists() and file_path.is_dir():
        raise ValueError("cannot overwrite a directory")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(args["content"], encoding="utf-8")
    return f"wrote {file_path.relative_to(Path(root).resolve())}"


def patch_file(root, args):
    """精确替换文件片段；参数为 Path 根目录和含 path/old_text/new_text 的 dict，返回 str 操作结果。"""
    file_path = path(root, args["path"])
    if not file_path.is_file():
        raise ValueError(f"not a file: {args['path']}")
    content = file_path.read_text(encoding="utf-8")
    occurrences = content.count(args["old_text"])
    if occurrences != 1:
        raise ValueError(f"old_text must occur exactly once (found {occurrences})")
    file_path.write_text(content.replace(args["old_text"], args["new_text"]), encoding="utf-8")
    return f"patched {file_path.relative_to(Path(root).resolve())}"


def run_shell(root, args):
    """在工作区执行 Shell 命令；参数为 Path 根目录和含 command/timeout 的 dict，返回 stdout/stderr str。"""
    command = args["command"]
    timeout = int(args.get("timeout", 30))
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must not be empty")
    if not 1 <= timeout <= 120:
        raise ValueError("timeout must be between 1 and 120 seconds")
    try:
        result = subprocess.run(command, cwd=root, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return f"timed out after {timeout}s\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}"
    output = (result.stdout + result.stderr).strip()
    return f"exit code: {result.returncode}\n{output}" if output else f"exit code: {result.returncode}"


def validate_tool(root, name, args):
    """校验工具参数并返回原参数；参数为 Path 根目录、str 工具名和 dict 参数，返回 dict。"""
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    required = {
        "read_file": ("path",), "search": ("pattern",), "write_file": ("path", "content"),
        "patch_file": ("path", "old_text", "new_text"), "run_shell": ("command",),
    }.get(name, ())
    for key in required:
        if key not in args:
            raise ValueError(f"missing argument: {key}")
    if name in {"read_file", "write_file", "patch_file"}:
        path(root, args["path"])
    if name == "read_file":
        start, end = int(args.get("start", 1)), int(args.get("end", 10**9))
        if start < 1 or end < start:
            raise ValueError("line range is invalid")
    if name == "search" and not args["pattern"]:
        raise ValueError("pattern must not be empty")
    if name == "run_shell":
        timeout = int(args.get("timeout", 30))
        if not str(args["command"]).strip():
            raise ValueError("command must not be empty")
        if not 1 <= timeout <= 120:
            raise ValueError("timeout must be between 1 and 120 seconds")
    return args


def build_tools(agent):
    """构造工具定义表；参数为 MyAgent 实例，返回含 schema/risky/description/run 的 dict。"""
    return {
        "list_files": {"schema": {}, "risky": False, "description": "list workspace files", "run": list_files},
        "read_file": {"schema": {"path": "str", "start": "int?", "end": "int?"}, "risky": False, "description": "read UTF-8 lines", "run": read_file},
        "search": {"schema": {"pattern": "str"}, "risky": False, "description": "search text recursively", "run": search},
        "write_file": {"schema": {"path": "str", "content": "str"}, "risky": True, "description": "create or replace a file", "run": write_file},
        "patch_file": {"schema": {"path": "str", "old_text": "str", "new_text": "str"}, "risky": True, "description": "replace one exact text occurrence", "run": patch_file},
        "run_shell": {"schema": {"command": "str", "timeout": "int?"}, "risky": True, "description": "run a shell command", "run": run_shell},
    }
