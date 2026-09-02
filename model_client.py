import json
import os
import threading
import urllib.error
import urllib.request


def load_env_file(path):
    """加载简单 KEY=VALUE 配置；参数为 str 文件路径，返回 None 且不覆盖现有环境变量。"""
    env_path = os.path.expanduser(path)
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if name and name not in os.environ:
                os.environ[name] = value.strip('"\'')


class OpenAICompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature=0.2, top_p=0.9, timeout=60):
        """初始化兼容客户端；参数为模型、地址、密钥及采样/超时配置，返回 None。"""
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self._response_state = threading.local()

    @property
    def last_response_metadata(self):
        """读取当前线程最近响应元数据；参数为 self，返回 dict。"""
        return getattr(self._response_state, "metadata", {})

    def complete(self, prompt, max_new_tokens):
        """请求聊天补全；参数为 str Prompt 和 int token 上限，返回模型文本 str。"""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.base_url + ("/chat/completions" if self.base_url.endswith("/v1") else "/v1/chat/completions"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model request failed with HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"could not reach model at {self.base_url}: {exc}") from exc
        try:
            choice = data["choices"][0]
            message = choice["message"]
            self._response_state.metadata = {
                "finish_reason": choice.get("finish_reason"),
                "usage": data.get("usage", {}),
                "reasoning_content": message.get("reasoning_content") or "",
            }
            return message.get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("model response did not contain choices[0].message.content") from exc


class OllamaModelClient:
    def __init__(self, model, host, temperature=0.2, top_p=0.9, timeout=60):
        """初始化 Ollama 客户端；参数为模型、主机及采样/超时配置，返回 None。"""
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self._response_state = threading.local()

    @property
    def last_response_metadata(self):
        """读取当前线程最近响应元数据；参数为 self，返回 dict。"""
        return getattr(self._response_state, "metadata", {})

    def complete(self, prompt, max_new_tokens):
        """请求 Ollama 生成；参数为 str Prompt 和 int token 上限，返回模型文本 str。"""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_new_tokens, "temperature": self.temperature, "top_p": self.top_p},
        }
        request = urllib.request.Request(
            self.host + "/api/generate", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed with HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"could not reach Ollama at {self.host}: {exc}") from exc
        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        self._response_state.metadata = {
            "finish_reason": data.get("done_reason"),
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
            },
            "reasoning_content": data.get("thinking") or "",
        }
        return data.get("response", "")


class FakeModelClient:
    """按顺序返回预设文本的测试客户端。"""

    def __init__(self, outputs):
        """初始化输出队列；参数为可迭代的 str 输出，返回 None。"""
        self.outputs = iter(outputs)
        self.last_response_metadata = {}

    def complete(self, prompt, max_new_tokens):
        """返回下一条预设响应；参数为 Prompt 和 token 上限，返回 str。"""
        try:
            return next(self.outputs)
        except StopIteration as exc:
            raise RuntimeError("fake model has no more outputs") from exc


def build_model_client(args):
    """按 CLI 配置构造客户端；参数为 argparse Namespace，返回兼容客户端对象。"""
    if args.provider == "ollama":
        return OllamaModelClient(args.model, args.host, args.temperature, args.top_p, args.timeout)
    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    if not api_key:
        raise RuntimeError(f"API key environment variable {args.api_key_env!r} is not set")
    return OpenAICompatibleModelClient(args.model, args.base_url, api_key, args.temperature, args.top_p, args.timeout)
