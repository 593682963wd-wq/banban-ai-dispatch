"""核心分配算法。

把当天「有航班的飞机」分到 2 个放行席位，最小化多目标加权不均衡分数。
目标覆盖 7 条业务规则：
  1 总量 + 时段A/B 均衡    2 C类机场均分        3 B类机场均分
  4 长沙出港 + 讲解量均衡  5 过夜目的地均分      6 同机场/同区域均分
  7 C/B同目的地拆分 + 过夜落地窗口拆分 + 相近起飞时刻分散 + 交接班敏感窗口均衡

飞机数 N 一般 13~16，采用「全枚举 + 去对称」精确求最优；N 超过阈值时退化为
随机重启局部搜索，保证可用性。
"""
from __future__ import annotations

import random
from typing import Optional

from .airports import OVERNIGHT_DESTS
from .fleet import fleet_sort_key
from .models import Aircraft, AllocationConfig, AllocationResult, SeatPlan

# 超过该飞机数改用局部搜索（2^(N-1) 过大时）
ENUM_LIMIT = 20


def _segment_counts(ac: Aircraft, config: AllocationConfig) -> tuple[int, int]:
    return ac.n_segment(
        config.split_minutes,
        config.segment_start_minutes,
        config.segment_end_minutes,
        config.service_date,
    )


def _aircraft_features(aircrafts: list[Aircraft], config: AllocationConfig):
    """预计算每架飞机的指标特征 + 冲突对 + 键集合。"""
    feats = []
    region_keys: set[str] = set()
    dest_keys: set[str] = set()
    c_dest_keys: set[str] = set()
    b_dest_keys: set[str] = set()
    n_windows = len(config.handover_windows)

    for ac in aircrafts:
        seg_a, seg_b = _segment_counts(ac, config)
        rc = ac.region_counts()
        dc = ac.dest_counts()
        cdc = ac.c_class_dest_counts()
        bdc = ac.b_class_dest_counts()
        region_keys |= set(rc.keys())
        dest_keys |= set(dc.keys())
        c_dest_keys |= set(cdc.keys())
        b_dest_keys |= set(bdc.keys())
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
            "cs": ac.n_changsha_dep,
            "brief": ac.n_briefing,
            "ov": ac.overnight_key,
            "ov_arr": ac.final_arrival_time,
            "rc": rc,
            "dc": dc,
            "cdc": cdc,
            "bdc": bdc,
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

    # 同一过夜地的最后落地时刻若在前后 2 小时窗口内，尽量拆到两个席位。
    overnight_landing_conflict: list[tuple[int, int]] = []
    for i in range(len(aircrafts)):
        ov_i = feats[i]["ov"]
        arr_i = feats[i]["ov_arr"]
        if not ov_i or arr_i is None:
            continue
        for j in range(i + 1, len(aircrafts)):
            if feats[j]["ov"] != ov_i or feats[j]["ov_arr"] is None:
                continue
            delta_min = abs((feats[j]["ov_arr"] - arr_i).total_seconds()) / 60
            if delta_min <= config.overnight_arrival_window_min:
                overnight_landing_conflict.append((i, j))

    return (
        feats,
        sorted(region_keys),
        sorted(dest_keys),
        sorted(c_dest_keys),
        sorted(b_dest_keys),
        conflict,
        overnight_landing_conflict,
    )


def _score_assignment(
    feats,
    region_keys,
    dest_keys,
    c_dest_keys,
    b_dest_keys,
    conflict,
    overnight_landing_conflict,
    assignment,
    config,
):
    """对一个 0/1 分配计算 (score, metrics, group_totals)。"""
    n_windows = len(config.handover_windows)
    g = [
        {"n": 0, "a": 0, "b": 0, "c": 0, "bc": 0, "cs": 0, "brief": 0,
         "ov": {}, "rc": {}, "dc": {}, "cdc": {}, "bdc": {}, "hw": [0] * n_windows}
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
        grp["brief"] += f["brief"]
        if f["ov"]:
            grp["ov"][f["ov"]] = grp["ov"].get(f["ov"], 0) + 1
        for k, v in f["rc"].items():
            grp["rc"][k] = grp["rc"].get(k, 0) + v
        for k, v in f["dc"].items():
            grp["dc"][k] = grp["dc"].get(k, 0) + v
        for k, v in f["cdc"].items():
            grp["cdc"][k] = grp["cdc"].get(k, 0) + v
        for k, v in f["bdc"].items():
            grp["bdc"][k] = grp["bdc"].get(k, 0) + v
        for w in range(n_windows):
            grp["hw"][w] += f["hw"][w]

    d_total = abs(g[0]["n"] - g[1]["n"])
    d_seg_a = abs(g[0]["a"] - g[1]["a"])
    d_seg_b = abs(g[0]["b"] - g[1]["b"])
    d_c = abs(g[0]["c"] - g[1]["c"])
    d_bc = abs(g[0]["bc"] - g[1]["bc"])
    d_cs = abs(g[0]["cs"] - g[1]["cs"])
    d_brief = abs(g[0]["brief"] - g[1]["brief"])
    d_ov = sum(abs(g[0]["ov"].get(k, 0) - g[1]["ov"].get(k, 0)) for k in OVERNIGHT_DESTS)
    d_region = sum(abs(g[0]["rc"].get(k, 0) - g[1]["rc"].get(k, 0)) for k in region_keys)
    d_dest = sum(abs(g[0]["dc"].get(k, 0) - g[1]["dc"].get(k, 0)) for k in dest_keys)
    d_c_dest = sum(abs(g[0]["cdc"].get(k, 0) - g[1]["cdc"].get(k, 0)) for k in c_dest_keys)
    d_b_dest = sum(abs(g[0]["bdc"].get(k, 0) - g[1]["bdc"].get(k, 0)) for k in b_dest_keys)
    d_hw = sum(abs(g[0]["hw"][w] - g[1]["hw"][w]) for w in range(n_windows))

    gap = 0
    for (i, j) in conflict:
        if assignment[i] == assignment[j]:
            gap += 1

    overnight_gap = 0
    for (i, j) in overnight_landing_conflict:
        if assignment[i] == assignment[j]:
            overnight_gap += 1

    score = (
        config.w_total * d_total
        + config.w_segment * (d_seg_a + d_seg_b)
        + config.w_c_class * d_c
        + config.w_b_class * d_bc
        + config.w_changsha * d_cs
        + config.w_briefing * d_brief
        + config.w_overnight * d_ov
        + config.w_region * d_region
        + config.w_dest * d_dest
        + config.w_c_dest * d_c_dest
        + config.w_b_dest * d_b_dest
        + config.w_overnight_landing_window * overnight_gap
        + config.w_gap * gap
        + config.w_handover * d_hw
    )

    metrics = {
        "总航班数差": d_total,
        "时段A差": d_seg_a,
        "时段B差": d_seg_b,
        "C类机场差": d_c,
        "B类机场差": d_bc,
        "C类同目的地差": d_c_dest,
        "B类同目的地差": d_b_dest,
        "长沙出港差": d_cs,
        "讲解量差": d_brief,
        "过夜目的地差": d_ov,
        "过夜落地窗口冲突": overnight_gap,
        "区域差合计": d_region,
        "同机场差合计": d_dest,
        "相近时刻冲突": gap,
        "交接班窗口差": d_hw,
    }
    return score, metrics, g


def _segment_priority(metrics: dict) -> tuple[float, float, float, float]:
    """时段A/B 是首位目标：先压低单段最大差，再压低总差。"""
    d_seg_a = metrics["时段A差"]
    d_seg_b = metrics["时段B差"]
    return (max(d_seg_a, d_seg_b), d_seg_a + d_seg_b, d_seg_a, d_seg_b)


def _assignment_key(score, metrics, group_totals, assignment) -> tuple:
    """分配比较键。

    A/B 时段均衡先于所有其他综合得分，再用原有多目标分数细分。
    """
    return (
        *_segment_priority(metrics),
        score,
        abs(group_totals[0]["n"] - group_totals[1]["n"]),
        abs(sum(1 for a in assignment if a == 0) - sum(1 for a in assignment if a == 1)),
    )


def _iter_enumerate(n: int):
    """枚举所有分配，固定第 0 架在席位 0（去镜像对称）。"""
    for mask in range(0, 1 << (n - 1)):
        assignment = [0] * n
        for bit in range(n - 1):
            if mask & (1 << bit):
                assignment[bit + 1] = 1
        yield assignment


def _local_search(
    feats,
    region_keys,
    dest_keys,
    c_dest_keys,
    b_dest_keys,
    conflict,
    overnight_landing_conflict,
    n,
    config,
    restarts=40,
    iters=4000,
):
    """随机重启局部搜索（N 很大时的兜底）。"""
    best_assignment = None
    best_key = None
    rng = random.Random(20260605)
    for _ in range(restarts):
        assignment = [rng.randint(0, 1) for _ in range(n)]
        assignment[0] = 0
        score, metrics, g = _score_assignment(
            feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
            conflict, overnight_landing_conflict, assignment, config
        )
        cur_key = _assignment_key(score, metrics, g, assignment)
        improved = True
        steps = 0
        while improved and steps < iters:
            improved = False
            for i in range(1, n):
                assignment[i] ^= 1
                s2, m2, g2 = _score_assignment(
                    feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
                    conflict, overnight_landing_conflict, assignment, config
                )
                k2 = _assignment_key(s2, m2, g2, assignment)
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


def _add_aircraft_to_plan(ac: Aircraft, plan: SeatPlan, config: AllocationConfig) -> None:
    plan.tails.append(ac.tail)
    plan.n_flights += ac.n_flights
    a, b = _segment_counts(ac, config)
    plan.n_seg_a += a
    plan.n_seg_b += b
    plan.n_c_class += ac.n_c_class
    plan.n_b_class += ac.n_b_class
    plan.n_changsha_dep += ac.n_changsha_dep
    plan.n_briefing += ac.n_briefing
    if ac.n_flights == 0:
        plan.n_idle_aircraft += 1


def _assign_idle_aircraft(idle: list[Aircraft], seat1: SeatPlan, seat2: SeatPlan, config: AllocationConfig) -> None:
    """Distribute empty-task aircraft evenly while keeping output deterministic."""
    if not idle:
        return
    idle_sorted = sorted(idle, key=lambda ac: fleet_sort_key(ac.tail))
    start = 0 if len(seat1.tails) <= len(seat2.tails) else 1
    for idx, ac in enumerate(idle_sorted):
        side = (start + idx) % 2
        _add_aircraft_to_plan(ac, seat1 if side == 0 else seat2, config)


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
        _assign_idle_aircraft(idle, seat1, seat2, config)
        return AllocationResult(
            seat1=seat1, seat2=seat2, aircrafts=aircrafts, config=config,
            metrics={"空任务飞机差": abs(seat1.n_idle_aircraft - seat2.n_idle_aircraft)}, score=0.0,
            idle_tails=[ac.tail for ac in idle],
        )

    (
        feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
        conflict, overnight_landing_conflict,
    ) = _aircraft_features(active, config)

    best_assignment = None
    best_key = None
    if n <= ENUM_LIMIT:
        for assignment in _iter_enumerate(n):
            score, metrics, g = _score_assignment(
                feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
                conflict, overnight_landing_conflict, assignment, config
            )
            # tie-break：时段A/B首位均衡 → 综合分 → 总数差 → 飞机数差（更稳定均衡）
            key = _assignment_key(score, metrics, g, assignment)
            if best_key is None or key < best_key:
                best_key = key
                best_assignment = assignment[:]
    else:
        best_assignment = _local_search(
            feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
            conflict, overnight_landing_conflict, n, config
        )

    score, metrics, g = _score_assignment(
        feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
        conflict, overnight_landing_conflict, best_assignment, config
    )

    # 规约：席位1 取航班数较多的一组（与历史习惯无强绑定，仅保证稳定可读）
    swap = g[1]["n"] > g[0]["n"]
    for ac, asg in zip(active, best_assignment):
        side = asg ^ (1 if swap else 0)
        _add_aircraft_to_plan(ac, seat1 if side == 0 else seat2, config)

    _assign_idle_aircraft(idle, seat1, seat2, config)
    metrics["空任务飞机差"] = abs(seat1.n_idle_aircraft - seat2.n_idle_aircraft)

    result = AllocationResult(
        seat1=seat1, seat2=seat2, aircrafts=aircrafts, config=config,
        score=score, metrics=metrics, idle_tails=[ac.tail for ac in idle],
    )
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
    (
        feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
        conflict, overnight_landing_conflict,
    ) = _aircraft_features(active, config)
    score, metrics, _ = _score_assignment(
        feats, region_keys, dest_keys, c_dest_keys, b_dest_keys,
        conflict, overnight_landing_conflict, assignment, config
    )
    return score, metrics
