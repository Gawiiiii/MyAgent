import argparse
from pathlib import Path

from changes import format_diff
from model_client import build_model_client, load_env_file
from my_agent import MyAgent
from session import SessionStore
from workspace import WorkspaceContext

HELP_TEXT = """Available commands:
/help                 Show this detailed command reference.
/memory               Show the current task, files, and notes in working memory.
/session              Show the current session JSON file path.
/diff                 Show all active changes and their unified diffs.
/rollback [id]        Roll back the latest change, or the change with the given ID.
/audit [N]            Show the latest N audit events (default: 20).
/audit-clear          Delete all audit events for the current session.
/reset                Start a new empty session in the same workspace.
/exit                 Exit interactive mode.
/quit                 Exit interactive mode."""


def _one_line_task(session, limit=80):
    """生成会话任务摘要；参数为会话 dict 和长度，返回单行 str。"""
    task = str(session.get("memory", {}).get("task", "")).replace("\n", " ").strip()
    task = " ".join(task.split()) or "(no task)"
    return task if len(task) <= limit else task[: limit - 3] + "..."


def select_session(store, parser):
    """显示最近会话并读取选择；参数为存储器和解析器，返回会话 ID str。"""
    sessions = store.recent(5)
    if not sessions:
        parser.error("no session available to resume")
    print("Recent sessions:")
    for index, session in enumerate(sessions, 1):
        print(f"{index}. {session['id']}  {_one_line_task(session)}")
    choice = input(f"Select 1-{len(sessions)} or enter a displayed session ID: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(sessions):
        return sessions[int(choice) - 1]["id"]
    if any(session["id"] == choice for session in sessions):
        return choice
    parser.error("invalid session selection")


def run(argv=None):
    """解析命令行并运行 Agent；参数为可选 argv 列表，返回 None。"""
    parser = argparse.ArgumentParser(description="Minimal local MyAgent")
    parser.add_argument("message", nargs="?", default="")
    parser.add_argument("--cwd", default="./demo")
    parser.add_argument("--provider", choices=["openai-compatible", "ollama"], default="openai-compatible")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--env-file", default=".env", help="file containing KEY=VALUE settings")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--unlimited-tool-calls", action=argparse.BooleanOptionalAction, default=True, help="allow unlimited tool calls")
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--approval", choices=["ask", "auto", "never"], default="ask")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--resume", nargs="?", const="select", default="", help="session ID, latest, or omit the value to choose from five recent sessions")
    parser.add_argument("--max-depth", type=int, default=1, help="maximum delegation depth")
    parser.add_argument("--max-parallel-delegates", type=int, default=3, help="maximum parallel read-only delegates (1-8)")
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    workspace = WorkspaceContext.build(args.cwd)
    store = SessionStore(Path(workspace.cwd) / ".mini-coding-agent" / "sessions")
    def status(message):
        text = f"{message:<80}" if message else " " * 80
        print(f"\r{text}\r" if not message else f"\r{text}", end="", flush=True)

    common = {"max_steps": args.max_steps, "approval": args.approval, "max_new_tokens": args.max_new_tokens, "max_depth": args.max_depth, "max_parallel_delegates": args.max_parallel_delegates, "unlimited_tool_calls": args.unlimited_tool_calls, "status": status}
    session_id = ""
    if args.resume:
        if args.resume == "select":
            session_id = select_session(store, parser)
        else:
            session_id = store.latest() if args.resume == "latest" else args.resume
        if not session_id:
            parser.error("no session available to resume")
    client = build_model_client(args)
    if session_id:
        agent = MyAgent.from_session(client, workspace, store, session_id, **common)
    else:
        agent = MyAgent(client, workspace.cwd, workspace=workspace, session_store=store, **common)
    if args.message:
        try:
            print(f"<final>{agent.ask(args.message)}</final>")
        except RuntimeError as exc:
            print(f"error: {exc}")
        return
    print("MyAgent interactive mode. Type /help for commands, /exit to quit.")
    while True:
        try:
            message = input("my-agent> ").strip()
        except EOFError:
            break
        if message in {"/exit", "/quit"}:
            break
        if message == "/help":
            print(HELP_TEXT)
        elif message == "/memory":
            print(agent.session.get("memory", {}))
        elif message == "/session":
            print(store.path(agent.session["id"]))
        elif message == "/diff":
            if not agent.changes:
                print("no changes")
            else:
                for change in agent.changes:
                    print(f"[{change['id']}] {change['operation']} {change['path']}\n{format_diff(change['diff'])}")
        elif message.startswith("/rollback"):
            parts = message.split()
            if len(parts) > 2:
                print("error: usage /rollback [id]")
            else:
                print(agent.rollback(parts[1] if len(parts) == 2 else None))
        elif message.startswith("/audit-clear"):
            if message != "/audit-clear":
                print("error: usage /audit-clear")
            else:
                agent.audit_log.clear()
                print("audit cleared")
        elif message.startswith("/audit"):
            parts = message.split()
            if len(parts) > 2:
                print("error: usage /audit [N]")
            else:
                try:
                    limit = int(parts[1]) if len(parts) == 2 else 20
                    if limit < 1:
                        raise ValueError
                    for event in agent.audit_log.read(limit):
                        print(event)
                except ValueError:
                    print("error: audit limit must be a positive integer")
        elif message == "/reset":
            agent.reset()
            print("session reset")
        elif message:
            try:
                print(f"<final>{agent.ask(message)}</final>")
            except RuntimeError as exc:
                print(f"error: {exc}")


def main(argv=None):
    """运行 CLI 并将顶层模型错误显示为文本；参数为可选 argv，返回 None。"""
    try:
        run(argv)
    except RuntimeError as exc:
        print(f"error: {exc}")


if __name__ == "__main__":
    main()
