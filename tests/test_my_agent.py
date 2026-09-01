"""第五阶段统一测试入口，汇总前四阶段覆盖并加入最终功能测试。"""

from tests.basic_tests import CurrentVersionTests
from tests.stage3_tests import Stage3Tests
from tests.stage4_tests import Stage4Tests
from tests.stage5_tests import Stage5Tests
from tests.stage6_tests import Stage6Tests

__all__ = ["CurrentVersionTests", "Stage3Tests", "Stage4Tests", "Stage5Tests", "Stage6Tests"]
