"""带班 AI 分飞机 — 核心算法层 (core)

纯 Python 实现，不依赖任何 GUI / Web 框架，方便公司信息开发人员移植到任意环境。
对外主要接口：
    - parser.load_dynamic_list / build_aircrafts   读取动态列表 Excel → 数据模型
    - allocator.allocate                            执行席位分配
    - excel_writer.write_allocation_excel           导出分配结果 Excel
"""

from .models import Flight, Aircraft, AllocationConfig, AllocationResult, SeatPlan
from .allocator import allocate, evaluate_split
from .parser import load_dynamic_list, build_aircrafts, COLUMN_ALIASES

__all__ = [
    "Flight",
    "Aircraft",
    "AllocationConfig",
    "AllocationResult",
    "SeatPlan",
    "allocate",
    "evaluate_split",
    "load_dynamic_list",
    "build_aircrafts",
    "COLUMN_ALIASES",
]

__version__ = "1.0.0"
