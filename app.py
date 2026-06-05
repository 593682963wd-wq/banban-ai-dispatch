"""带班AI分飞机 — 网页版 / 本地版共用同一份代码。

上传次日动态列表（每架飞机当日全部航班），AI 自动把所有飞机均衡分配到
放行签派一 / 放行签派二两个席位，多目标兼顾：总任务量、时段忙闲、C/B 类
机场、区域分布、过夜地、相近时刻冲突、交接班窗口。
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from core.parser import (
    load_dynamic_list,
    resolve_columns,
    build_aircrafts,
    infer_date,
)
from core.models import AllocationConfig
from core.allocator import allocate
from core.excel_writer import build_excel_bytes
from core.airports import airport_name

APP_VERSION = "V 1.0.0"
AUTHOR = "王迪"
TECH_SUPPORT = "AI 智能分配"

st.set_page_config(
    page_title="带班AI分飞机",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────
# 主题（暗蓝赛博风，统一风格 + 席位灰/蓝配色）
# ─────────────────────────────────────────
st.markdown(
    """
<style>
:root{
  --bg:#0a0e17; --panel:#0d1520; --panel-strong:#0d2137;
  --line:#1a3a5c; --line-strong:#1a5276;
  --accent:#4fc3f7; --accent-2:#80d8ff;
  --text:#c0d8f0; --muted:#6d93b2;
  --ok:#66bb6a; --warn:#ffb74d; --bad:#ef5350;
  --seat1:#9aa3ad; --seat1-bg:rgba(231,233,236,.10);
  --seat2:#4fa3e0; --seat2-bg:rgba(189,215,238,.12);
}
html, body, [class*="css"]{
  font-family: "Menlo","Consolas","SF Mono","Monaco",monospace;
  color: var(--text);
}
.stApp{
  background: radial-gradient(circle at 100% -5%, #113052 0%, var(--bg) 35%);
}
.main .block-container{ max-width:1400px; padding-top:1.1rem; padding-bottom:1.4rem; }
section[data-testid="stSidebar"]{ display:none !important; }
button[kind="header"][aria-label*="sidebar" i]{ display:none !important; }

.main-header{
  position: relative; text-align: center;
  padding: 0.8rem 0 0.6rem 0;
  border-bottom: 1px solid var(--line); margin-bottom: 0.9rem;
}
.main-header h1{
  color: var(--accent); margin: 0; letter-spacing: 2px;
  font-size: 1.85rem; font-weight: 700;
}
.main-header p{ color: var(--muted); margin: 0.25rem 0 0 0; font-size: 0.82rem; letter-spacing: 1px; }
.header-meta{ position: absolute; top: 6px; right: 8px; text-align: right; line-height: 1.55; }
.header-meta .badge-version{
  display: inline-block; background: transparent; color: #50fa7b;
  border: 1px solid #50fa7b; border-radius: 12px; padding: 2px 14px;
  font-size: 0.78rem; font-weight: 700; font-family: "Menlo", monospace;
  letter-spacing: 2px; margin-bottom: 10px;
}
.header-meta table.credits{ margin-left:auto; border-collapse: collapse; }
.header-meta table.credits td{
  color: #4fc3f7; font-size: 0.78rem; font-weight: 700;
  font-family: "Menlo", monospace; letter-spacing: 1px; padding: 2px 0;
}
.header-meta table.credits td.t-label{ text-align:right; padding-right:2px; }
.header-meta table.credits td.t-colon{ text-align:center; padding:0 2px; }
.header-meta table.credits td.t-name{ text-align:left; padding-left:2px; }

.upload-hero{
  background: linear-gradient(135deg, rgba(79,195,247,.10) 0%, rgba(13,33,55,.6) 100%);
  border: 2px dashed var(--accent); border-radius: 14px;
  padding: 22px 28px 8px 28px; margin: 0 0 14px 0;
  box-shadow: 0 0 28px rgba(79,195,247,.15);
}
.upload-hero .hero-title{ color: var(--accent); font-size: 1.45rem; font-weight: 700; letter-spacing: 1px; margin: 0 0 4px 0; }
.upload-hero .hero-sub{ color: var(--muted); font-size: 0.9rem; margin: 0 0 10px 0; }

[data-testid="stFileUploader"] section{
  background: var(--panel) !important; border: 1.5px dashed var(--accent) !important;
  border-radius: 10px !important; min-height: 130px; padding: 18px !important;
}
[data-testid="stFileUploader"] section *{ color: var(--text) !important; }
[data-testid="stFileUploader"] section button{
  background: var(--accent) !important; color: #0a0e17 !important;
  font-weight: 700 !important; border: none !important; padding: .55rem 1.4rem !important;
}

.step-card{
  background: var(--panel); border: 1px solid var(--line);
  border-left: 3px solid var(--accent); border-radius: 8px;
  padding: 10px 16px; margin: 14px 0 8px 0;
}
.step-num{
  display: inline-flex; width: 24px; height: 24px; border-radius: 50%;
  background: var(--accent); color: #0a0e17; font-weight: 700;
  align-items: center; justify-content: center; margin-right: 10px; font-size: 0.85rem;
}
.step-title{ color: var(--accent); font-weight: 600; font-size: 1rem; }

/* 席位面板 */
.seat-grid{ display:flex; gap:16px; margin:10px 0 4px 0; flex-wrap:wrap; }
.seat-panel{ flex:1; min-width:320px; border-radius:12px; padding:16px 18px; }
.seat-panel.s1{ background:var(--seat1-bg); border:1px solid var(--seat1); }
.seat-panel.s2{ background:var(--seat2-bg); border:1px solid var(--seat2); }
.seat-panel .seat-name{ font-size:1.2rem; font-weight:700; letter-spacing:1px; margin-bottom:8px; }
.seat-panel.s1 .seat-name{ color:#cfd6dd; }
.seat-panel.s2 .seat-name{ color:#9ccdf5; }
.seat-stat{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
.seat-stat .kv{ background:rgba(255,255,255,.04); border:1px solid var(--line); border-radius:6px; padding:6px 10px; min-width:84px; }
.seat-stat .kv .k{ color:var(--muted); font-size:.72rem; letter-spacing:1px; }
.seat-stat .kv .v{ font-size:1.25rem; font-weight:700; }
.seat-panel.s1 .seat-stat .kv .v{ color:#dfe5ea; }
.seat-panel.s2 .seat-stat .kv .v{ color:#7fc0f3; }
.tail-chips{ display:flex; gap:6px; flex-wrap:wrap; }
.tail-chip{ font-size:.85rem; font-weight:700; padding:3px 9px; border-radius:6px; font-family:"Menlo",monospace; }
.seat-panel.s1 .tail-chip{ background:#e7e9ec; color:#2b2f33; }
.seat-panel.s2 .tail-chip{ background:#bdd7ee; color:#143a5c; }

.metric-strip{ display:flex; gap:12px; margin: 8px 0; flex-wrap:wrap; }
.metric-card{ flex:1; min-width:120px; background: var(--panel-strong); border:1px solid var(--line); border-radius:8px; padding:12px 16px; }
.metric-card .label{ color: var(--muted); font-size:.74rem; letter-spacing:1px; }
.metric-card .value{ color: var(--accent); font-size:1.6rem; font-weight:700; margin-top:2px; }
.metric-card .delta{ font-size:.72rem; color:var(--muted); margin-top:2px; }

.stButton > button, .stDownloadButton > button{
  background: var(--panel-strong) !important; color: var(--accent) !important;
  border: 1px solid var(--line-strong) !important; border-radius: 6px !important;
  font-weight: 600 !important; min-height: 2.4rem;
}
.stButton > button:hover, .stDownloadButton > button:hover{
  border-color: var(--accent) !important; background: #153d5e !important;
}
button[data-testid="stBaseButton-primary"]{
  background: linear-gradient(180deg, #1d6f3a 0%, #155a2c 100%) !important;
  color: #f0fff4 !important; border: 2px solid #50fa7b !important;
  font-weight: 700 !important; font-size: 1.05rem !important;
  min-height: 2.9rem !important; letter-spacing: 1px !important;
  box-shadow: 0 0 14px rgba(80,250,123,.3) !important;
}
h1,h2,h3,h4{ color: var(--accent) !important; letter-spacing: .5px; }
hr{ border-color: var(--line) !important; }
.stDataFrame{ border:1px solid var(--line) !important; border-radius:8px !important; }
details, .streamlit-expander{
  background: var(--panel) !important; border:1px solid var(--line) !important;
  border-radius: 8px !important; margin: 8px 0 !important;
}
details summary, .streamlit-expanderHeader{
  color: var(--accent) !important; font-weight: 600 !important; padding: 10px 14px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────
# 顶部标题
# ─────────────────────────────────────────
st.markdown(
    f"""
<div class="main-header">
    <div class="header-meta">
        <div class="badge-version">{APP_VERSION}</div>
        <table class="credits">
            <tr><td class="t-label">系统开发</td><td class="t-colon">：</td><td class="t-name">{AUTHOR}</td></tr>
            <tr><td class="t-label">分配引擎</td><td class="t-colon">：</td><td class="t-name">{TECH_SUPPORT}</td></tr>
        </table>
    </div>
    <h1>✈ 带班AI分飞机</h1>
    <p>ON-DUTY AI AIRCRAFT ALLOCATION · 放行签派席位智能均衡分配</p>
</div>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────
# 上传区
# ─────────────────────────────────────────
st.markdown(
    """
<div class="upload-hero">
  <div class="hero-title">📥 第一步 · 上传次日动态列表（Excel）</div>
  <div class="hero-sub">表格需包含：机号、机型、始发/到达机场（四字码）、起飞/到达时刻。系统会按机号汇总每架飞机当日全部航班，再做均衡分配。</div>
</div>
""",
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    label="上传动态列表 Excel",
    type=["xlsx", "xls"],
    accept_multiple_files=False,
    label_visibility="collapsed",
)

if not uploaded:
    st.info("👆 请先上传动态列表。一架飞机当天的所有航班会整体分到同一个席位。")
    with st.expander("📖 分配规则说明"):
        st.markdown(
            """
**分配单位 = 飞机（机号）**：一架飞机当天的全部航班作为一个整体，分给同一个席位，不拆分单个航班。

**AI 兼顾的均衡目标（多目标加权最优）**：
1. **总任务量** — 两席位航班总数尽量接近
2. **时段忙闲** — 上午 / 下午（按分时点切分）两席位都不过载
3. **C 类机场** — 高高原/复杂机场航班均分（最受关注）
4. **B 类机场** — 次复杂机场航班均分
5. **区域分布** — 东北/华东/云南/西南… 各方向不集中在一个席位
6. **过夜地** — 长沙/昆明/无锡等过夜目的地均衡
7. **相近时刻冲突** — 同一时刻附近起飞的飞机尽量分到不同席位，避免一个人同时盯多架
8. **交接班窗口** — 交接班时段两席位任务都不扎堆

历史人工分配通常牺牲总数均衡（差 0~4）去换取 C/B 类与区域均衡；本系统在所有维度上同时优化，实测综合均衡度优于人工。
"""
        )
    st.stop()

# ─────────────────────────────────────────
# 第二步 · 解析
# ─────────────────────────────────────────
st.markdown(
    '<div class="step-card"><span class="step-num">2</span><span class="step-title">解析动态列表</span></div>',
    unsafe_allow_html=True,
)

try:
    raw = uploaded.read()
    df = load_dynamic_list(BytesIO(raw))
    cmap = resolve_columns(list(df.columns))
    date = infer_date(df, cmap)
    aircrafts = build_aircrafts(df, cmap)
except Exception as e:  # noqa: BLE001
    st.error(f"解析失败：{e}")
    st.stop()

active = [ac for ac in aircrafts if ac.n_flights > 0]
total_flights = sum(ac.n_flights for ac in active)

c1, c2, c3, c4 = st.columns(4)
c1.markdown(
    f'<div class="metric-card"><div class="label">飞机总数</div><div class="value">{len(active)}</div></div>',
    unsafe_allow_html=True,
)
c2.markdown(
    f'<div class="metric-card"><div class="label">航班总数</div><div class="value">{total_flights}</div></div>',
    unsafe_allow_html=True,
)
c3.markdown(
    f'<div class="metric-card"><div class="label">C 类航班</div><div class="value">{sum(ac.n_c_class for ac in active)}</div></div>',
    unsafe_allow_html=True,
)
c4.markdown(
    f'<div class="metric-card"><div class="label">识别日期</div><div class="value" style="font-size:1.2rem;">{date.strftime("%m-%d") if date else "—"}</div></div>',
    unsafe_allow_html=True,
)

# 分时切分设置
default_cfg = AllocationConfig.for_date(date)
default_split = default_cfg.split_minutes
split_label_default = f"{default_split // 60:02d}:{default_split % 60:02d}"
colA, colB = st.columns([1, 3])
with colA:
    split_choice = st.selectbox(
        "时段切分点",
        options=["13:30", "16:30", "自动（按日期）"],
        index=2,
        help="6/1 起默认 13:30，之前默认 16:30；可手动指定。",
    )

if split_choice == "13:30":
    split_minutes = 810
elif split_choice == "16:30":
    split_minutes = 990
else:
    split_minutes = default_split

cfg = AllocationConfig.for_date(date)
cfg.split_minutes = split_minutes

# ─────────────────────────────────────────
# 第三步 · 运行分配
# ─────────────────────────────────────────
st.markdown(
    '<div class="step-card"><span class="step-num">3</span><span class="step-title">AI 均衡分配</span></div>',
    unsafe_allow_html=True,
)

run = st.button("🚀  开始智能分配", type="primary", use_container_width=False)

if run or st.session_state.get("dispatch_done"):
    if run:
        with st.spinner("正在多目标寻优，枚举所有均衡方案…"):
            result = allocate(aircrafts, cfg)
        st.session_state["dispatch_result_bytes"] = build_excel_bytes(result)
        st.session_state["dispatch_done"] = True
        st.session_state["_result_obj"] = result
    result = st.session_state["_result_obj"]

    s1, s2 = result.seat1, result.seat2
    st.success(
        f"✅ 分配完成：{s1.name} {s1.n_flights} 班 / {s2.name} {s2.n_flights} 班 ·"
        f" 综合均衡得分 {result.score:.0f}（越低越均衡）"
    )

    # 席位面板
    def _chips(tails):
        return "".join(f'<span class="tail-chip">{t}</span>' for t in tails)

    def _seat_html(seat, cls):
        return f"""
<div class="seat-panel {cls}">
  <div class="seat-name">{seat.name}</div>
  <div class="seat-stat">
    <div class="kv"><div class="k">飞机</div><div class="v">{len(seat.tails)}</div></div>
    <div class="kv"><div class="k">航班</div><div class="v">{seat.n_flights}</div></div>
    <div class="kv"><div class="k">时段A</div><div class="v">{seat.n_seg_a}</div></div>
    <div class="kv"><div class="k">时段B</div><div class="v">{seat.n_seg_b}</div></div>
    <div class="kv"><div class="k">C类</div><div class="v">{seat.n_c_class}</div></div>
    <div class="kv"><div class="k">B类</div><div class="v">{seat.n_b_class}</div></div>
  </div>
  <div class="tail-chips">{_chips(seat.tails)}</div>
</div>
"""

    st.markdown(
        f'<div class="seat-grid">{_seat_html(s1, "s1")}{_seat_html(s2, "s2")}</div>',
        unsafe_allow_html=True,
    )

    # 均衡指标
    with st.expander("📊 均衡指标明细（两席位各维度差值，越小越均衡）", expanded=True):
        mdf = pd.DataFrame(
            [{"指标": k, "差值": v} for k, v in result.metrics.items()]
        )
        st.dataframe(mdf, use_container_width=True, hide_index=True)

    # 航班明细
    st.markdown(
        '<div class="step-card"><span class="step-num">4</span><span class="step-title">航班明细</span></div>',
        unsafe_allow_html=True,
    )
    by_tail = {ac.tail: ac for ac in result.aircrafts}
    rows = []
    for seat in (s1, s2):
        for tail in seat.tails:
            ac = by_tail.get(tail)
            if ac is None:
                continue
            a, b = ac.n_segment(cfg.split_minutes)
            legs = " ; ".join(
                f"{f.dep_hhmm} {airport_name(f.dep_icao)}→{airport_name(f.arr_icao)}"
                for f in ac.flights
            )
            rows.append({
                "席位": seat.name, "机号": ac.tail, "机型": ac.ac_type,
                "航班数": ac.n_flights, "时段A": a, "时段B": b,
                "C类": ac.n_c_class, "B类": ac.n_b_class,
                "过夜地": airport_name(ac.overnight_dest) if ac.overnight_dest else "",
                "航段": legs,
            })
    detail = pd.DataFrame(rows)

    def _row_style(row):
        if row["席位"] == s1.name:
            return ["background-color: rgba(231,233,236,.10)"] * len(row)
        return ["background-color: rgba(189,215,238,.12)"] * len(row)

    st.dataframe(
        detail.style.apply(_row_style, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    if result.idle_tails:
        st.caption("📍 当日无航班（停场/备用）：" + "、".join(result.idle_tails))

    # 下载
    st.download_button(
        "⬇️  下载分配结果 Excel",
        data=st.session_state["dispatch_result_bytes"],
        file_name=f"带班分飞机_{date.strftime('%m%d') if date else '结果'}_{APP_VERSION}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )

st.markdown(
    f"<div style='text-align:center; color:var(--muted); font-size:.78rem; padding: 12px 0;'>"
    f"带班AI分飞机 {APP_VERSION} · 系统开发 {AUTHOR} · 放行签派席位智能均衡"
    f"</div>",
    unsafe_allow_html=True,
)
