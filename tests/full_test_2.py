"""第二轮真实 API 集成测试及逐轮调用记录；需设置 MYAGENT_RUN_FULL_TESTS=1 才运行。"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_client import OpenAICompatibleModelClient, load_env_file
from my_agent import MyAgent
from parser import parse
from session import SessionStore
from workspace import WorkspaceContext

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HAS_CONFIGURATION = bool(os.environ.get("DEEPSEEK_API_KEY")) or (PROJECT_ROOT / ".env").exists()
RUN_REAL_API = os.environ.get("MYAGENT_RUN_FULL_TESTS") == "1" and HAS_CONFIGURATION


class TracingModelClient:
    """包装真实模型客户端并记录每轮原始反馈。"""

    def __init__(self, client):
        """初始化记录器；参数为真实模型客户端，返回 None。"""
        self.client = client
        self.calls = []

    def complete(self, prompt, max_new_tokens):
        """调用真实模型并保存反馈；参数为 Prompt 和 token 上限，返回模型原始 str。"""
        output = self.client.complete(prompt, max_new_tokens)
        self.calls.append({"prompt": prompt, "output": output})
        return output


@unittest.skipUnless(RUN_REAL_API, "set MYAGENT_RUN_FULL_TESTS=1 and configure .env/API key")
class MultiStageRealAPITests(unittest.TestCase):
    """验证真实模型多阶段编程任务并输出逐轮轨迹。"""

    def setUp(self):
        """准备真实客户端和轨迹容器；无参数，返回 None。"""
        load_env_file(str(PROJECT_ROOT / ".env"))
        self.tracer = TracingModelClient(OpenAICompatibleModelClient("deepseek-v4-flash", "https://api.deepseek.com", os.environ["DEEPSEEK_API_KEY"]))
        self.trace = []

    def tearDown(self):
        """在测试结束后写入每轮轨迹日志；无参数，返回 None。"""
        if not self.trace:
            return
        log_path = Path(os.environ.get("MYAGENT_FULL_TEST_LOG", PROJECT_ROOT / "full_test_2_trace.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"=== {self.id()} ==="]
        for index, item in enumerate(self.trace, 1):
            lines.extend([
                f"Round {index} user request: {item['request']}",
                f"Round {index} tool call: {item['tool'] or '(none)'}",
                f"Round {index} LLM output:\n{item['output']}",
                "",
            ])
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write("\n".join(lines) + "\n")

    def ask_stage(self, agent, request):
        """执行一个多轮阶段并记录每次 LLM 反馈；参数为 MyAgent 和用户请求 str，返回最终答案 str。"""
        start = len(self.tracer.calls)
        answer = agent.ask(request)
        for call in self.tracer.calls[start:]:
            parsed = parse(call["output"])
            tool = f"{parsed.get('name')} {parsed.get('args')}" if parsed.get("kind") == "tool" else ""
            self.trace.append({"request": request, "tool": tool, "output": call["output"]})
        return answer

    def new_agent(self, directory, store=None, workspace=None):
        """创建启用真实客户端的 Agent；参数为工作区和可选会话组件，返回 MyAgent。"""
        workspace = workspace or WorkspaceContext.build(directory)
        store = store or SessionStore(Path(directory) / ".mini-coding-agent" / "sessions")
        return MyAgent(self.tracer, directory, approval="auto", max_steps=12, workspace=workspace, session_store=store)

    def assert_stable(self, answer):
        """检查阶段有最终文本且不抛出循环停止异常；参数为答案 str，返回 None。"""
        self.assertTrue(answer.strip())
        self.assertNotIn("Traceback", answer)

    def test_multi_stage_create_test_fix_and_report(self):
        """真实执行创建、测试、修复二分查找的三阶段任务；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            agent = self.new_agent(directory)
            self.assert_stable(self.ask_stage(agent, "创建 binary_search.py，实现升序整数列表的二分查找函数，并说明接口。"))
            self.assertTrue(Path(directory, "binary_search.py").exists())
            self.assert_stable(self.ask_stage(agent, "为 binary_search.py 创建 pytest 测试，覆盖命中、未命中和空列表，并运行 pytest。"))
            self.assertTrue(any(path.name.startswith("test_") for path in Path(directory).iterdir()))
            self.assert_stable(self.ask_stage(agent, "检查实现和测试结果；若失败请精确修改并重新运行 pytest，最后总结。"))

    def test_multi_stage_resume_and_append(self):
        """真实验证会话保存、恢复和跨阶段文件追加；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / ".mini-coding-agent" / "sessions")
            workspace = WorkspaceContext.build(directory)
            agent = self.new_agent(directory, store, workspace)
            self.assert_stable(self.ask_stage(agent, "创建 notes.txt，写入阶段一完成。"))
            resumed = MyAgent.from_session(self.tracer, workspace, store, agent.session["id"], approval="auto", max_steps=10)
            self.assert_stable(self.ask_stage(resumed, "读取 notes.txt，追加阶段二完成，并确认原内容仍在。"))
            content = Path(directory, "notes.txt").read_text(encoding="utf-8")
            self.assertIn("阶段一", content)
            self.assertIn("阶段二", content)

    def test_multi_stage_failure_recovery_and_never_boundary(self):
        """真实验证失败修复和 never 审批边界；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            agent = self.new_agent(directory)
            self.assert_stable(self.ask_stage(agent, "创建 broken.py 和 test_broken.py，让测试先失败并运行 pytest。"))
            self.assert_stable(self.ask_stage(agent, "分析失败原因，用 patch_file 修复并重新运行测试直到通过。"))
            safe = MyAgent(self.tracer, directory, approval="never", max_steps=6)
            self.assert_stable(self.ask_stage(safe, "请创建 should_not_exist.txt，内容为 blocked。"))
            self.assertFalse(Path(directory, "should_not_exist.txt").exists())


if __name__ == "__main__":
    unittest.main()
