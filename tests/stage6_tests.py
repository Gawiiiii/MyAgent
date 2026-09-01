import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from my_agent import MyAgent


class ParallelClient:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def complete(self, prompt, _tokens):
        task = prompt.split("Current request: ", 1)[-1]
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        time.sleep(0.03)
        with self.lock:
            self.active -= 1
        return f"<final>{task}</final>"


class Stage6Tests(unittest.TestCase):
    def test_parallel_results_are_ordered_and_run_concurrently(self):
        with TemporaryDirectory() as directory:
            client = ParallelClient()
            agent = MyAgent(client, directory, max_parallel_delegates=3)
            result = agent.run_tool("delegate_parallel", {"tasks": ["first", "second", "third"]})
            self.assertIn("delegate_result[1]: first", result)
            self.assertIn("delegate_result[2]: second", result)
            self.assertIn("delegate_result[3]: third", result)
            self.assertGreaterEqual(client.maximum_active, 2)

    def test_parallel_limits_and_invalid_tasks_are_errors(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(ParallelClient(), directory, max_parallel_delegates=2)
            self.assertIn("at most 2", agent.run_tool("delegate_parallel", {"tasks": ["a", "b", "c"]}))
            self.assertIn("task must not be empty", agent.run_tool("delegate_parallel", {"tasks": ["ok", " "]}))

    def test_parallel_child_is_read_only_and_depth_is_bounded(self):
        with TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text("read-only", encoding="utf-8")
            agent = MyAgent(ParallelClient(), directory, max_depth=0)
            self.assertIn("maximum delegation depth", agent.run_tool("delegate_parallel", {"tasks": ["inspect"]}))
            child = MyAgent(ParallelClient(), directory, read_only=True)
            self.assertEqual(set(child.tools), {"list_files", "read_file", "search"})


if __name__ == "__main__":
    unittest.main()
