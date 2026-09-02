import unittest
from tempfile import TemporaryDirectory

from context import clip, history_text, middle
from my_agent import MyAgent


class SequenceClient:
    """按顺序返回预设模型结果的测试客户端。"""

    def __init__(self, outputs):
        """初始化响应队列；参数为 str 列表，返回 None。"""
        self.outputs = iter(outputs)

    def complete(self, _prompt, _tokens):
        """返回下一条模型结果；参数为 Prompt 和 token 上限，返回 str。"""
        return next(self.outputs)


class Stage4Tests(unittest.TestCase):
    def test_empty_final_is_retry_and_retry_does_not_consume_tool_steps(self):
        """验证空最终答案重试且不消耗工具步数；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            client = SequenceClient(["<final></final>", "", "<final>recovered</final>"])
            agent = MyAgent(client, directory, max_steps=1)
            self.assertEqual(agent.ask("task"), "recovered")

    def test_repeated_retry_read_returns_error_and_stops(self):
        """验证连续 retry 读取达到上限后反馈错误；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            call = '<tool>{"name":"read_file","args":{"path":"missing.py","retry":true}}</tool>'
            client = SequenceClient([call, call, call, call, "<final>stopped retrying</final>"])
            agent = MyAgent(client, directory)
            answer = agent.ask("repeat")
            self.assertEqual(answer, "stopped retrying")
            self.assertIn("repeated retry read limit", "\n".join(item["content"] for item in agent.session["history"] if item["role"] == "tool"))

    def test_context_limits_old_output_and_deduplicates_reads(self):
        """验证历史长度限制、旧输出压缩和读取去重；无参数，返回 None。"""
        history = [
            {"role": "tool", "name": "read_file", "args": {"path": "a.py"}, "content": "same"},
            {"role": "tool", "name": "read_file", "args": {"path": "a.py"}, "content": "same"},
            {"role": "tool", "name": "write_file", "args": {"path": "a.py"}, "content": "updated"},
            {"role": "tool", "name": "read_file", "args": {"path": "a.py"}, "content": "new"},
        ]
        rendered = history_text(history)
        self.assertEqual(rendered.count("same"), 1)
        self.assertIn("new", rendered)
        self.assertLessEqual(len(clip("x" * 5000)), 4040)
        self.assertEqual(len(middle("x" * 100, 20)), 20)


if __name__ == "__main__":
    unittest.main()
