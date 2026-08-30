import argparse

from model_client import build_model_client, load_env_file
from my_agent import MyAgent


def main(argv=None):
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
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--approval", choices=["ask", "auto", "never"], default="ask")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    if not args.message:
        parser.error("a user request is required")
    load_env_file(args.env_file)
    answer = MyAgent(build_model_client(args), args.cwd, args.max_steps, args.approval, args.max_new_tokens).ask(args.message)
    print(f"<final>{answer}</final>")


if __name__ == "__main__":
    main()
