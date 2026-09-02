import argparse
from pathlib import Path

from model_client import build_model_client, load_env_file
from my_agent import MyAgent
from session import SessionStore
from workspace import WorkspaceContext


def run(argv=None):
    """解析命令行并运行 Agent；参数为可选 argv 列表，返回 None。"""
    parser = argparse.ArgumentParser(description="Minimal local MyAgent")
    parser.add_argument("message", nargs="?", default="")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--provider", choices=["openai-compatible", "ollama"], default="openai-compatible")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--env-file", default=".env", help="file containing KEY=VALUE settings")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--approval", choices=["ask", "auto", "never"], default="ask")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--resume", default="", help="session ID or latest")
    parser.add_argument("--max-depth", type=int, default=1, help="maximum delegation depth")
    parser.add_argument("--max-parallel-delegates", type=int, default=3, help="maximum parallel read-only delegates (1-8)")
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    workspace = WorkspaceContext.build(args.cwd)
    store = SessionStore(Path(workspace.repo_root) / ".mini-coding-agent" / "sessions")
    client = build_model_client(args)
    common = {"max_steps": args.max_steps, "approval": args.approval, "max_new_tokens": args.max_new_tokens, "max_depth": args.max_depth, "max_parallel_delegates": args.max_parallel_delegates}
    if args.resume:
        session_id = store.latest() if args.resume == "latest" else args.resume
        if not session_id:
            parser.error("no session available to resume")
        agent = MyAgent.from_session(client, workspace, store, session_id, **common)
    else:
        agent = MyAgent(client, workspace.repo_root, workspace=workspace, session_store=store, **common)
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
            print("/help /memory /session /diff /rollback [id] /audit [N] /audit-clear /reset /exit /quit")
        elif message == "/memory":
            print(agent.session.get("memory", {}))
        elif message == "/session":
            print(store.path(agent.session["id"]))
        elif message == "/diff":
            if not agent.changes:
                print("no changes")
            else:
                for change in agent.changes:
                    print(f"[{change['id']}] {change['operation']} {change['path']}\n{change['diff']}")
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
