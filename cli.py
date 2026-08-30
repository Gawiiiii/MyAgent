import argparse

from model_client import build_model_client
from my_agent import MyAgent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Minimal local MyAgent")
    parser.add_argument("message", nargs="?", default="")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--provider", choices=["openai-compatible", "ollama"], default="ollama")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    if not args.message:
        parser.error("a user request is required")
    answer = MyAgent(build_model_client(args), args.cwd, args.max_steps).ask(args.message)
    print(f"<final>{answer}</final>")


if __name__ == "__main__":
    main()
