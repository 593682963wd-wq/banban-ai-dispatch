"""机场分类与区域映射。

分类口径来自带班分飞机业务规则（C 类 / B 类机场、区域前缀、过夜目的地等）。
全部以 ICAO 四字码为准（动态列表的「始发」「到达」列即 ICAO）。
"""
from __future__ import annotations

# 主基地（长沙黄花）
HOME_BASE = "ZGHA"

# C 类机场（规则 2，最高均分优先级）
C_CLASS_AIRPORTS = {
    "ZPLC",  # 临沧
    "ZPCW",  # 沧源
    "ZUTC",  # 腾冲
    "ZPBS",  # 保山
    "ZPJH",  # 西双版纳
    "ZPMS",  # 芒市（德宏）
    "ZPLJ",  # 丽江
    "ZLXN",  # 西宁
    "ZGDY",  # 张家界
    "ZYDD",  # 丹东
    "ZGLB",  # 荔波
    "ZPSM",  # 普洱
    "ZPDL",  # 大理
}

# B 类机场（规则 3，均分优先级低于 C 类）
B_CLASS_AIRPORTS = {
    "ZBLA",  # 长治
    "ZYYJ",  # 延吉
    "ZULP",  # 六盘水
    "ZPPP",  # 昆明
    "ZLLL",  # 兰州（中川）
    "ZLIC",  # 银川
    "ZLJQ",  # 嘉峪关
    "ZUKJ",  # 凯里
    "ZSSR",  # 上饶
    "ZGHZ",  # 惠州
    "ZLYA",  # 延安
    "ZHSY",  # 十堰
    "ZSZS",  # 舟山
}

# 区域前缀（规则 6，到达 ICAO 前两位）
REGION_PREFIX = {
    "ZY": "东北",
    "ZS": "华东",
    "ZP": "云南",
    "ZW": "新疆",
    "ZB": "华北",
    "ZG": "华南",
    "ZU": "西南",
    "ZL": "西北",
    "ZH": "华中",
    "ZJ": "海南",
}

# 过夜目的地（规则 5）：最后一班按这三个目的地均分
OVERNIGHT_DESTS = {
    "ZGHA": "长沙",
    "ZPPP": "昆明",
    "ZSWX": "无锡",
}

# ICAO → 中文名（仅用于界面展示，未知则回退显示 ICAO 本身）
AIRPORT_NAMES = {
    "ZGHA": "长沙", "ZPPP": "昆明", "ZSWX": "无锡", "ZGSZ": "深圳",
    "ZBAD": "北京大兴", "ZBHH": "呼和浩特", "ZBLA": "长治",
    "ZGBH": "北海", "ZGCD": "常德", "ZGDY": "张家界", "ZGSD": "揭阳潮汕",
    "ZJHK": "海口", "ZLLL": "兰州", "ZLXN": "西宁", "ZLYA": "延安",
    "ZPBS": "保山", "ZPJH": "西双版纳", "ZPLJ": "丽江", "ZPMS": "芒市",
    "ZSCN": "南昌", "ZSHC": "杭州", "ZSJG": "井冈山", "ZSJN": "济南",
    "ZSNJ": "南京", "ZSNT": "南通", "ZSQD": "青岛", "ZSSR": "上饶",
    "ZSWZ": "温州", "ZUGY": "贵阳", "ZUTR": "铜仁", "ZUYB": "宜宾",
    "ZUZY": "遵义", "ZWSC": "莎车", "ZWTL": "吐鲁番", "ZYCC": "长春",
    "ZYHB": "哈尔滨", "ZYTX": "沈阳", "ZPLC": "临沧", "ZPCW": "沧源",
    "ZUTC": "腾冲", "ZYDD": "丹东", "ZGLB": "荔波", "ZPSM": "普洱",
    "ZPDL": "大理", "ZYYJ": "延吉", "ZULP": "六盘水", "ZLIC": "银川",
    "ZLJQ": "嘉峪关", "ZUKJ": "凯里", "ZGHZ": "惠州", "ZHSY": "十堰",
    "ZSZS": "舟山",
}


def region_of(icao: str) -> str:
    """返回到达机场所属区域键（ICAO 前两位）。未知前缀直接用前两位作为键。"""
    if not icao:
        return "??"
    return icao[:2].upper()


def region_name(icao: str) -> str:
    """返回区域中文名（用于展示）。"""
    return REGION_PREFIX.get(region_of(icao), region_of(icao))


def airport_name(icao: str) -> str:
    """返回机场中文名，未知回退 ICAO。"""
    if not icao:
        return ""
    return AIRPORT_NAMES.get(icao.upper(), icao.upper())


def is_c_class(icao: str) -> bool:
    return bool(icao) and icao.upper() in C_CLASS_AIRPORTS


def is_b_class(icao: str) -> bool:
    return bool(icao) and icao.upper() in B_CLASS_AIRPORTS
