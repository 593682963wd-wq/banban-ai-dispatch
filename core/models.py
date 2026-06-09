"""数据模型：航班、飞机、分配配置与结果。

纯数据类，不含 IO / UI 逻辑，便于跨环境移植与单元测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import airports


@dataclass
class Flight:
    """单个航班任务（动态列表的一行）。"""

    tail: str                      # 机号，如 30AN
    ac_type: str                   # 机型，如 A320N-C6Y180
    dep_icao: str                  # 始发 ICAO
    arr_icao: str                  # 到达 ICAO
    dep_time: Optional[datetime]   # 局飞（计划起飞）
    arr_time: Optional[datetime]   # 局达（计划到达）
    row_index: int = -1            # 源表行号（便于追溯）

    @property
    def dep_minutes(self) -> Optional[int]:
        """起飞时刻（当日 0 点起的分钟数）。无时间返回 None。"""
        if self.dep_time is None:
            return None
        return self.dep_time.hour * 60 + self.dep_time.minute

    @property
    def dep_hhmm(self) -> str:
        return self.dep_time.strftime("%H:%M") if self.dep_time else "--:--"

    @property
    def arr_hhmm(self) -> str:
        return self.arr_time.strftime("%H:%M") if self.arr_time else "--:--"

    @property
    def is_c_class(self) -> bool:
        return airports.is_c_class(self.arr_icao)

    @property
    def is_b_class(self) -> bool:
        return airports.is_b_class(self.arr_icao)

    @property
    def region(self) -> str:
        return airports.region_of(self.arr_icao)


@dataclass
class Aircraft:
    """一架飞机（机号）当天的全部航班任务。分配的最小单位。"""

    tail: str
    ac_type: str
    flights: list[Flight] = field(default_factory=list)

    def sort_flights(self) -> None:
        self.flights.sort(key=lambda f: (f.dep_minutes is None, f.dep_minutes or 0))

    # ── 机型大类（用于界面按 A320/A319/A321 分组）──
    @property
    def type_group(self) -> str:
        t = (self.ac_type or "").upper()
        for fam in ("A319", "A320", "A321", "A330", "A350", "B737", "B738"):
            if fam in t:
                return fam
        # 兜底：取字母+前 3 位数字
        head = t.split("-")[0]
        return head or "其他"

    @property
    def n_flights(self) -> int:
        return len(self.flights)

    @property
    def n_c_class(self) -> int:
        return sum(1 for f in self.flights if f.is_c_class)

    @property
    def n_b_class(self) -> int:
        return sum(1 for f in self.flights if f.is_b_class)

    @property
    def n_changsha_dep(self) -> int:
        """长沙出港航班数。用于均衡基地出港监控与讲解工作量。"""
        return sum(1 for f in self.flights if f.dep_icao == airports.HOME_BASE)

    @property
    def n_briefing(self) -> int:
        """需要重点讲解/关注的航班量。

        当前口径：长沙出港、C 类目的地、B 类目的地任一命中即计 1 次。
        """
        return sum(
            1
            for f in self.flights
            if f.dep_icao == airports.HOME_BASE or f.is_c_class or f.is_b_class
        )

    def n_segment(self, split_minutes: int) -> tuple[int, int]:
        """返回 (时段A航班数, 时段B航班数)。
        时段A = 起飞时刻 <= split_minutes；时段B = > split_minutes。
        无起飞时间的航班计入时段A（多为早班）。
        """
        a = b = 0
        for f in self.flights:
            m = f.dep_minutes
            if m is None or m <= split_minutes:
                a += 1
            else:
                b += 1
        return a, b

    @property
    def first_changsha_dep(self) -> Optional[int]:
        """当天最早一班从长沙(ZGHA)起飞的起飞时刻（分钟）。无则 None。规则 4。"""
        times = [
            f.dep_minutes
            for f in self.flights
            if f.dep_icao == airports.HOME_BASE and f.dep_minutes is not None
        ]
        return min(times) if times else None

    @property
    def overnight_dest(self) -> Optional[str]:
        """当天最后一班的到达 ICAO（过夜地）。规则 5。"""
        if not self.flights:
            return None
        last = max(
            self.flights,
            key=lambda f: (f.dep_minutes is not None, f.dep_minutes or -1),
        )
        return last.arr_icao

    @property
    def overnight_key(self) -> Optional[str]:
        """过夜地若属于 长沙/昆明/无锡 之一，返回其 ICAO；否则 None。"""
        d = self.overnight_dest
        return d if d in airports.OVERNIGHT_DESTS else None

    def region_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.flights:
            out[f.region] = out.get(f.region, 0) + 1
        return out

    def dest_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.flights:
            out[f.arr_icao] = out.get(f.arr_icao, 0) + 1
        return out

    def c_class_dest_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.flights:
            if f.is_c_class:
                out[f.arr_icao] = out.get(f.arr_icao, 0) + 1
        return out

    def b_class_dest_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.flights:
            if f.is_b_class:
                out[f.arr_icao] = out.get(f.arr_icao, 0) + 1
        return out


@dataclass
class AllocationConfig:
    """分配参数。所有权重与时段均可在界面调整。"""

    # 时段分界（分钟，自 0 点）。6/1 起默认 13:30=810；6/1 前 16:30=990。
    split_minutes: int = 810

    # 交接班后敏感窗口（分钟区间，左开右闭近似）。规则 7。
    handover_windows: tuple[tuple[int, int], ...] = (
        (480, 510),   # 08:00–08:30
        (810, 840),   # 13:30–14:00
    )

    # 相近起飞时刻阈值（分钟）。同席位内间隔小于该值视为冲突。规则 7。
    gap_threshold_min: int = 5

    # ── 各目标权重（最小化两席位指标差）──
    w_total: float = 10.0       # 总航班数差
    w_segment: float = 8.0      # 时段A/B 各自的差
    w_c_class: float = 6.0      # C 类机场（规则 2）
    w_b_class: float = 4.0      # B 类机场（规则 3，低于 C 类）
    w_changsha: float = 5.0     # 长沙出港航班
    w_briefing: float = 5.0     # 讲解量
    w_overnight: float = 3.0    # 过夜目的地（规则 5）
    w_region: float = 2.0       # 同区域（规则 6）
    w_dest: float = 2.0         # 同机场（规则 6）
    w_c_dest: float = 8.0       # C 类同目的地机场
    w_b_dest: float = 5.0       # B 类同目的地机场
    w_gap: float = 1.0          # 相近时刻冲突（规则 7）
    w_handover: float = 3.0     # 交接班敏感窗口（规则 7）

    @staticmethod
    def for_date(dt: Optional[datetime]) -> "AllocationConfig":
        """按日期返回默认时段：6/1(含)起 13:30，之前 16:30。"""
        cfg = AllocationConfig()
        if dt is not None and (dt.month, dt.day) < (6, 1):
            cfg.split_minutes = 990  # 16:30
        else:
            cfg.split_minutes = 810  # 13:30
        return cfg


@dataclass
class SeatPlan:
    """单个放行席位的分配结果。"""

    name: str
    tails: list[str] = field(default_factory=list)
    n_flights: int = 0
    n_seg_a: int = 0
    n_seg_b: int = 0
    n_c_class: int = 0
    n_b_class: int = 0
    n_changsha_dep: int = 0
    n_briefing: int = 0
    n_idle_aircraft: int = 0


@dataclass
class AllocationResult:
    """完整分配结果。"""

    seat1: SeatPlan
    seat2: SeatPlan
    aircrafts: list[Aircraft]
    config: AllocationConfig
    score: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)
    idle_tails: list[str] = field(default_factory=list)  # 当天无航班的飞机

    @property
    def total_flights(self) -> int:
        return self.seat1.n_flights + self.seat2.n_flights
