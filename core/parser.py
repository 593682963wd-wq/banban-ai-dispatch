"""动态列表 Excel 解析。

负责把代班主任导出的「动态列表」Excel 转成 Flight / Aircraft 数据模型。
对列名做容错（不同系统导出的表头可能略有差异）。
"""
from __future__ import annotations

import warnings
from datetime import datetime
from typing import Optional

import pandas as pd

from .fleet import KNOWN_FLEET_TAILS, fleet_sort_key
from .models import Aircraft, Flight

# 关注列 → 可能的表头别名（全部小写比较，去空格）
COLUMN_ALIASES: dict[str, list[str]] = {
    "tail": ["机号", "机尾号", "注册号", "尾号", "飞机号"],
    "ac_type": ["机型", "机型代码", "型别"],
    "dep_icao": ["始发", "始发站", "始发机场", "起飞机场", "出发站", "出发"],
    "dep_time": ["局飞", "计划起飞", "计划离港", "预计起飞", "计划起飞时间"],
    "arr_icao": ["到达", "到达站", "到达机场", "目的地", "落地机场"],
    "arr_time": ["局达", "计划到达", "计划落地", "预计到达", "计划到达时间"],
}


def _norm(s: object) -> str:
    return str(s).strip().replace(" ", "").lower()


def resolve_columns(columns: list[str]) -> dict[str, str]:
    """把 DataFrame 列名解析到标准字段名。返回 {field: 实际列名}。"""
    norm_map = {_norm(c): c for c in columns}
    resolved: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = _norm(alias)
            if key in norm_map:
                resolved[field] = norm_map[key]
                break
    return resolved


def load_dynamic_list(path_or_buffer, sheet_name=0) -> pd.DataFrame:
    """读取动态列表 Excel 为 DataFrame（默认首个 sheet，表头在首行）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(path_or_buffer, sheet_name=sheet_name, header=0)
    return df


def _parse_time(value: object) -> Optional[datetime]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def _clean_icao(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().upper()


def _clean_tail(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().upper()


def build_aircrafts(
    df: pd.DataFrame,
    column_map: Optional[dict[str, str]] = None,
    known_tails: Optional[tuple[str, ...]] = KNOWN_FLEET_TAILS,
) -> list[Aircraft]:
    """把 DataFrame 转成按机号聚合的 Aircraft 列表。

    只保留有机号的行；只有机号、没有航班信息的行记为空任务飞机。
    known_tails 默认补齐当前 17 架固定机队，缺席于动态列表的机号也会作为
    空任务飞机进入分配。
    """
    if column_map is None:
        column_map = resolve_columns(list(df.columns))

    missing = [f for f in ("tail", "dep_icao", "arr_icao") if f not in column_map]
    if missing:
        raise ValueError(
            f"动态列表缺少必要列：{missing}。已识别列：{column_map}。"
            f"请确认表头包含 机号/始发/到达。"
        )

    c_tail = column_map["tail"]
    c_type = column_map.get("ac_type")
    c_dep = column_map["dep_icao"]
    c_arr = column_map["arr_icao"]
    c_dept = column_map.get("dep_time")
    c_arrt = column_map.get("arr_time")

    by_tail: dict[str, Aircraft] = {}
    for idx, row in df.iterrows():
        tail = _clean_tail(row[c_tail])
        if not tail or tail.lower() in ("nan", "none"):
            continue
        ac_type = str(row[c_type]).strip() if c_type and pd.notna(row[c_type]) else ""
        if tail not in by_tail:
            by_tail[tail] = Aircraft(tail=tail, ac_type=ac_type)
        ac = by_tail[tail]
        if not ac.ac_type and ac_type:
            ac.ac_type = ac_type

        dep_icao = _clean_icao(row[c_dep])
        arr_icao = _clean_icao(row[c_arr])
        dep_time = _parse_time(row[c_dept]) if c_dept else None
        arr_time = _parse_time(row[c_arrt]) if c_arrt else None

        if not any((dep_icao, arr_icao, dep_time, arr_time)):
            continue

        flight = Flight(
            tail=tail,
            ac_type=ac_type,
            dep_icao=dep_icao,
            arr_icao=arr_icao,
            dep_time=dep_time,
            arr_time=arr_time,
            row_index=int(idx) if isinstance(idx, (int,)) else -1,
        )
        ac.flights.append(flight)

    if known_tails:
        for tail in known_tails:
            clean_tail = _clean_tail(tail)
            if clean_tail and clean_tail not in by_tail:
                by_tail[clean_tail] = Aircraft(tail=clean_tail, ac_type="")

    aircrafts = list(by_tail.values())
    for ac in aircrafts:
        ac.sort_flights()
    # 稳定排序：机型大类 → 机号，方便界面展示与去对称
    aircrafts.sort(key=lambda a: (a.n_flights == 0, a.type_group, fleet_sort_key(a.tail)))
    return aircrafts


def infer_date(df: pd.DataFrame, column_map: Optional[dict[str, str]] = None) -> Optional[datetime]:
    """从局飞/局达列推断航班日期（取众数日期），用于决定默认时段。"""
    if column_map is None:
        column_map = resolve_columns(list(df.columns))
    for key in ("dep_time", "arr_time"):
        col = column_map.get(key)
        if not col:
            continue
        dates: dict = {}
        for v in df[col]:
            dt = _parse_time(v)
            if dt is not None:
                d = dt.date()
                dates[d] = dates.get(d, 0) + 1
        if dates:
            best = max(dates.items(), key=lambda kv: kv[1])[0]
            return datetime(best.year, best.month, best.day)
    return None
