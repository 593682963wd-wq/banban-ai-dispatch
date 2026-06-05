"""核心分配算法。

把当天「有航班的飞机」分到 2 个放行席位，最小化多目标加权不均衡分数。
目标覆盖 7 条业务规则：
  1 总量 + 时段A/B 均衡    2 C类机场均分        3 B类机场均分
  4 长沙首班均衡           5 过夜目的地均分      6 同机场/同区域均分
  7 相近起飞时刻分散 + 交接班敏感窗口均衡

飞机数 N 一般 13~16，采用「全枚举 + 去对称」精确求最优；N 超过阈值时退化为
随机重启局部搜索，保证可用性。
"""
from __future__ import annotations

import random
from typing import Optional

from .airports import OVERNIGHT_DESTS
from .models import Aircraft, AllocationConfig, AllocationResult, SeatPlan

# 超过该飞机数改用局部搜索（2^(N-1) 过大时）
ENUM_LIMIT = 20


def _aircraft_features(aircrafts: list[Aircraft], config: AllocationConfig):
    """预计算每架飞机的指标特征 + 冲突对 + 键集合。"""
    feats = []
    region_keys: set[str] = set()
    dest_keys: set[str] = set()
    n_windows = len(config.handover_windows)

    for ac in aircrafts:
        seg_a, seg_b = ac.n_segment(config.split_minutes)
        rc = ac.region_counts()
        dc = ac.dest_counts()
        region_keys |= set(rc.keys())
        dest_keys |= set(dc.keys())
        hw = [0] * n_windows
        for f in ac.flights:
            m = f.dep_minutes
            if m is None:
                continue
            for wi, (lo, hi) in enumerate(config.handover_windows):
                if lo < m <= hi:
                    hw[wi] += 1
        feats.append({
            "n": ac.n_flights,
            "a": seg_a,
            "b": seg_b,
            "c": ac.n_c_class,
            "bc": ac.n_b_class,
            "cs": 1 if ac.first_changsha_dep is not None else 0,
            "ov": ac.overnight_key,
            "rc": rc,
            "dc": dc,
            "hw": hw,
        })

    # 相近起飞时刻冲突对（不同飞机、起飞时刻差 < 阈值）
    flights_idx: list[tuple[int, int]] = []
    for i, ac in enumerate(aircrafts):
        for f in ac.flights:
            if f.dep_minutes is not None:
                flights_idx.append((f.dep_minutes, i))
    flights_idx.sort()
    conflict: list[tuple[int, int]] = []
    for x in range(len(flights_idx)):
        tx, ix = flights_idx[x]
        for y in range(x + 1, len(flights_idx)):
            ty, iy = flights_idx[y]
            if ty - tx >= config.gap_threshold_min:
                break
            if ix != iy:
                conflict.append((ix, iy))

    return feats, sorted(region_keys), sorted(dest_keys), conflict


def _score_assignment(feats, region_keys, dest_keys, conflict, assignment, config):
    """对一个 0/1 分配计算 (score, metrics, group_totals)。"""
    n_windows = len(config.handover_windows)
    g = [
        {"n": 0, "a": 0, "b": 0, "c": 0, "bc": 0, "cs": 0,
         "ov": {}, "rc": {}, "dc": {}, "hw": [0] * n_windows}
        for _ in range(2)
    ]
    for i, asg in enumerate(assignment):
        f = feats[i]
        grp = g[asg]
        grp["n"] += f["n"]
        grp["a"] += f["a"]
        grp["b"] += f["b"]
        grp["c"] += f["c"]
        grp["bc"] += f["bc"]
        grp["cs"] += f["cs"]
        if f["ov"]:
            grp["ov"][f["ov"]] = grp["ov"].get(f["ov"], 0) + 1
        for k, v in f["rc"].items():
            grp["rc"][k] = grp["rc"].get(k, 0) + v
        for k, v in f["dc"].items():
            grp["dc"][k] = grp["dc"].get(k, 0) + v
        for w in range(n_windows):
            grp["hw"][w] += f["hw"][w]

    d_total = abs(g[0]["n"] - g[1]["n"])
    d_seg_a = abs(g[0]["a"] - g[1]["a"])
    d_seg_b = abs(g[0]["b"] - g[1]["b"])
    d_c = abs(g[0]["c"] - g[1]["c"])
    d_bc = abs(g[0]["bc"] - g[1]["bc"])
    d_cs = abs(g[0]["cs"] - g[1]["cs"])
    d_ov = sum(abs(g[0]["ov"].get(k, 0) - g[1]["ov"].get(k, 0)) for k in OVERNIGHT_DESTS)
    d_region = sum(abs(g[0]["rc"].get(k, 0) - g[1]["rc"].get(k, 0)) for k in region_keys)
    d_dest = sum(abs(g[0]["dc"].get(k, 0) - g[1]["dc"].get(k, 0)) for k in dest_keys)
    d_hw = sum(abs(g[0]["hw"][w] - g[1]["hw"][w]) for w in range(n_windows))

    gap = 0
    for (i, j) in conflict:
        if assignment[i] == assignment[j]:
            gap += 1

    score = (
        config.w_total * d_total
        + config.w_segment * (d_seg_a + d_seg_b)
        + config.w_c_class * d_c
        + config.w_b_class * d_bc
        + config.w_changsha * d_cs
        + config.w_overnight * d_ov
        + config.w_region * d_region
        + config.w_dest * d_dest
        + config.w_gap * gap
        + config.w_handover * d_hw
    )

    metrics = {
        "总航班数差": d_total,
        "时段A差": d_seg_a,
        "时段B差": d_seg_b,
        "C类机场差": d_c,
        "B类机场差": d_bc,
        "长沙首班差": d_cs,
        "过夜目的地差": d_ov,
        "区域差合计": d_region,
        "同机场差合计": d_dest,
        "相近时刻冲突": gap,
        "交接班窗口差": d_hw,
    }
    return score, metrics, g


def _iter_enumerate(n: int):
    """枚举所有分配，固定第 0 架在席位 0（去镜像对称）。"""
    for mask in range(0, 1 << (n - 1)):
        assignment = [0] * n
        for bit in range(n - 1):
            if mask & (1 << bit):
                assignment[bit + 1] = 1
        yield assignment


def _local_search(feats, region_keys, dest_keys, conflict, n, config, restarts=40, iters=4000):
    """随机重启局部搜索（N 很大时的兜底）。"""
    best_assignment = None
    best_key = None
    rng = random.Random(20260605)
    for _ in range(restarts):
        assignment = [rng.randint(0, 1) for _ in range(n)]
        assignment[0] = 0
        score, metrics, g = _score_assignment(feats, region_keys, dest_keys, conflict, assignment, config)
        cur_key = (score, abs(g[0]["n"] - g[1]["n"]))
        improved = True
        steps = 0
        while improved and steps < iters:
            improved = False
            for i in range(1, n):
                assignment[i] ^= 1
                s2, m2, g2 = _score_assignment(feats, region_keys, dest_keys, conflict, assignment, config)
                k2 = (s2, abs(g2[0]["n"] - g2[1]["n"]))
                if k2 < cur_key:
                    cur_key = k2
                    improved = True
                else:
                    assignment[i] ^= 1
                steps += 1
        if best_key is None or cur_key < best_key:
            best_key = cur_key
            best_assignment = assignment[:]
    return best_assignment


def allocate(aircrafts: list[Aircraft], config: Optional[AllocationConfig] = None) -> AllocationResult:
    """主入口：返回最优席位分配。"""
    if config is None:
        config = AllocationConfig()

    active = [ac for ac in aircrafts if ac.n_flights > 0]
    idle = [ac for ac in aircrafts if ac.n_flights == 0]
    n = len(active)

    seat1 = SeatPlan(name="放行席位1")
    seat2 = SeatPlan(name="放行席位2")

    if n == 0:
        return AllocationResult(
            seat1=seat1, seat2=seat2, aircrafts=aircrafts, config=config,
            metrics={}, score=0.0,
        )

    feats, region_keys, dest_keys, conflict = _aircraft_features(active, config)

    best_assignment = None
    best_key = None
    if n <= ENUM_LIMIT:
        for assignment in _iter_enumerate(n):
            score, metrics, g = _score_assignment(
                feats, region_keys, dest_keys, conflict, assignment, config
            )
            # tie-break：分数 → 总数差 → 飞机数差（更稳定均衡）
            key = (score, abs(g[0]["n"] - g[1]["n"]), abs(
                sum(1 for a in assignment if a == 0) - sum(1 for a in assignment if a == 1)
            ))
            if best_key is None or key < best_key:
                best_key = key
                best_assignment = assignment[:]
    else:
        best_assignment = _local_search(feats, region_keys, dest_keys, conflict, n, config)

    score, metrics, g = _score_assignment(
        feats, region_keys, dest_keys, conflict, best_assignment, config
    )

    # 规约：席位1 取航班数较多的一组（与历史习惯无强绑定，仅保证稳定可读）
    swap = g[1]["n"] > g[0]["n"]
    for ac, asg in zip(active, best_assignment):
        side = asg ^ (1 if swap else 0)
        plan = seat1 if side == 0 else seat2
        plan.tails.append(ac.tail)
        plan.n_flights += ac.n_flights
        a, b = ac.n_segment(config.split_minutes)
        plan.n_seg_a += a
        plan.n_seg_b += b
        plan.n_c_class += ac.n_c_class
        plan.n_b_class += ac.n_b_class

    result = AllocationResult(
        seat1=seat1, seat2=seat2, aircrafts=aircrafts, config=config,
        score=score, metrics=metrics,
    )
    result.idle_tails = [ac.tail for ac in idle]
    return result


def evaluate_split(aircrafts: list[Aircraft], assignment: list[int],
                   config: Optional[AllocationConfig] = None) -> tuple[float, dict]:
    """对给定的 0/1 分配（仅含有航班飞机，顺序与传入一致）复算分数与指标。

    用于验证：把历史人工分配喂进来，看各项不均衡指标。
    """
    if config is None:
        config = AllocationConfig()
    active = [ac for ac in aircrafts if ac.n_flights > 0]
    if len(assignment) != len(active):
        raise ValueError(
            f"assignment 长度 {len(assignment)} 与有航班飞机数 {len(active)} 不一致"
        )
    feats, region_keys, dest_keys, conflict = _aircraft_features(active, config)
    score, metrics, _ = _score_assignment(
        feats, region_keys, dest_keys, conflict, assignment, config
    )
    return score, metrics
