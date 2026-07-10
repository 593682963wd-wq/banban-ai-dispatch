"""带班AI分飞机 — PySide6 桌面主窗口。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.airports import airport_name
from core.allocator import allocate
from core.excel_writer import write_allocation_excel
from core.models import AllocationConfig
from core.parser import build_aircrafts, infer_date, load_dynamic_list, resolve_columns

APP_VERSION = "V 1.1.2"
AUTHOR = "王迪"
CO_CREATOR = "刘泓妤"

SEAT1_COLOR = "#E7E9EC"  # 浅灰 → 放行签派一
SEAT2_COLOR = "#BDD7EE"  # 浅蓝 → 放行签派二

DARK_STYLE = """
QMainWindow, QWidget { background:#0a0e17; color:#c0d8f0;
    font-family:"PingFang SC","Menlo","Microsoft YaHei"; font-size:13px; }
QGroupBox { border:1px solid #1a3a5c; border-radius:8px; margin-top:14px;
    padding:10px; font-weight:700; color:#4fc3f7; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; }
QLineEdit, QComboBox { background:#0d1520; border:1px solid #1a3a5c;
    border-radius:6px; padding:6px 8px; color:#c0d8f0; }
QComboBox QAbstractItemView { background:#0d1520; color:#c0d8f0;
    selection-background-color:#153d5e; }
QPushButton { background:#0d2137; color:#4fc3f7; border:1px solid #1a5276;
    border-radius:6px; padding:7px 16px; font-weight:600; }
QPushButton:hover { background:#153d5e; border-color:#4fc3f7; }
QPushButton:disabled { color:#46637c; border-color:#1a3a5c; }
QPushButton#primary { background:#155a2c; color:#f0fff4; border:2px solid #50fa7b;
    font-size:14px; font-weight:700; }
QPushButton#primary:hover { background:#1d6f3a; }
QProgressBar { background:#0d1520; border:1px solid #1a3a5c; border-radius:6px;
    text-align:center; color:#c0d8f0; height:18px; }
QProgressBar::chunk { background:#4fc3f7; border-radius:5px; }
QTableWidget { background:#0d1520; gridline-color:#1a3a5c; border:1px solid #1a3a5c;
    border-radius:8px; }
QHeaderView::section { background:#1F4E79; color:#fff; padding:5px;
    border:none; font-weight:700; }
QTableWidget::item { color:#1a1a1a; }
QTextEdit { background:#0d1520; border:1px solid #1a3a5c; border-radius:8px;
    color:#8fb6d6; font-family:"Menlo","Consolas"; font-size:12px; }
QLabel { color:#c0d8f0; }
"""


class AllocateWorker(QThread):
    """后台跑分配，避免阻塞 UI。"""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, aircrafts, cfg):
        super().__init__()
        self.aircrafts = aircrafts
        self.cfg = cfg

    def run(self):
        try:
            result = allocate(self.aircrafts, self.cfg)
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    DETAIL_COLS = ["席位", "机号", "机型", "航班数", "空任务", "时段A", "时段B",
                   "C类", "B类", "长沙出港", "讲解量", "过夜地", "航段明细"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"带班AI分飞机  {APP_VERSION}")
        self.resize(1280, 840)
        self.setStyleSheet(DARK_STYLE)

        self.result = None
        self.date = None
        self.worker: AllocateWorker | None = None
        self._build_ui()

    # ── UI ──
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # 顶部标题
        header = QLabel(
            f"<div style='text-align:center;'>"
            f"<span style='color:#4fc3f7; font-size:24px; font-weight:700; letter-spacing:2px;'>"
            f"✈ 带班AI分飞机</span><br>"
            f"<span style='color:#6d93b2; font-size:12px;'>放行签派席位智能均衡分配 · "
            f"系统开发 {AUTHOR} · 共创 {CO_CREATOR} · {APP_VERSION}</span></div>"
        )
        header.setTextFormat(Qt.RichText)
        root.addWidget(header)

        # 控制区
        ctrl_box = QGroupBox("① 选择动态列表 · 设置")
        ctrl = QVBoxLayout(ctrl_box)
        row1 = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择次日动态列表 Excel（含 机号/机型/始发/到达/局飞/局达）")
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._pick_file)
        row1.addWidget(QLabel("动态列表："))
        row1.addWidget(self.path_edit, 1)
        row1.addWidget(btn_browse)
        ctrl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("时段切分点："))
        self.split_combo = QComboBox()
        self.split_combo.addItems(["自动（按日期）", "13:30", "16:30"])
        row2.addWidget(self.split_combo)
        row2.addStretch(1)
        self.btn_run = QPushButton("🚀 开始智能分配")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self._run)
        self.btn_export = QPushButton("⬇ 导出 Excel")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_excel)
        row2.addWidget(self.btn_run)
        row2.addWidget(self.btn_export)
        ctrl.addLayout(row2)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        ctrl.addWidget(self.progress)
        root.addWidget(ctrl_box)

        # 席位汇总
        sum_box = QGroupBox("② 席位分配概览")
        sum_l = QVBoxLayout(sum_box)
        self.summary_label = QLabel("等待分配…")
        self.summary_label.setTextFormat(Qt.RichText)
        self.summary_label.setWordWrap(True)
        sum_l.addWidget(self.summary_label)
        root.addWidget(sum_box)

        # 明细表
        detail_box = QGroupBox("③ 航班明细")
        det_l = QVBoxLayout(detail_box)
        self.table = QTableWidget(0, len(self.DETAIL_COLS))
        self.table.setHorizontalHeaderLabels(self.DETAIL_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        for i in range(len(self.DETAIL_COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(len(self.DETAIL_COLS) - 1, QHeaderView.Stretch)
        det_l.addWidget(self.table)
        root.addWidget(detail_box, 1)

        # 日志
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        root.addWidget(self.log)

    # ── 交互 ──
    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择动态列表", "", "Excel 文件 (*.xlsx *.xls)"
        )
        if path:
            self.path_edit.setText(path)

    def _log_msg(self, msg: str):
        self.log.append(msg)

    def _run(self):
        path = self.path_edit.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "提示", "请先选择有效的动态列表 Excel。")
            return
        try:
            df = load_dynamic_list(path)
            cmap = resolve_columns(list(df.columns))
            self.date = infer_date(df, cmap)
            aircrafts = build_aircrafts(df, cmap)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "解析失败", str(e))
            return

        active = [ac for ac in aircrafts if ac.n_flights > 0]
        if not active:
            QMessageBox.warning(self, "提示", "未解析到任何航班，请检查表头与数据。")
            return

        cfg = AllocationConfig.for_date(self.date)
        choice = self.split_combo.currentText()
        if choice == "13:30":
            cfg.split_minutes = 810
        elif choice == "16:30":
            cfg.split_minutes = 990
        split_txt = f"{cfg.split_minutes // 60:02d}:{cfg.split_minutes % 60:02d}"

        self._log_msg(
            f"解析成功：{len(active)} 架飞机，"
            f"空任务 {len([ac for ac in aircrafts if ac.n_flights == 0])} 架，"
            f"{sum(ac.n_flights for ac in active)} 个航班，"
            f"日期 {self.date.strftime('%m-%d') if self.date else '未知'}，"
            f"切分点 {split_txt}。开始分配…"
        )
        self.progress.setRange(0, 0)  # 忙碌动画
        self.btn_run.setEnabled(False)
        self.btn_export.setEnabled(False)

        self.worker = AllocateWorker(aircrafts, cfg)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, msg: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_run.setEnabled(True)
        QMessageBox.critical(self, "分配失败", msg)
        self._log_msg(f"✗ 分配失败：{msg}")

    def _on_done(self, result):
        self.result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.btn_run.setEnabled(True)
        self.btn_export.setEnabled(True)

        s1, s2 = result.seat1, result.seat2
        self.summary_label.setText(self._summary_html(s1, s2, result))
        self._fill_table(result)
        self._log_msg(
            f"✓ 分配完成：{s1.name} {s1.n_flights} 班 / {s2.name} {s2.n_flights} 班，"
            f"空任务 {s1.n_idle_aircraft}/{s2.n_idle_aircraft} 架，"
            f"综合均衡得分 {result.score:.0f}（越低越均衡）。"
        )
        if result.idle_tails:
            self._log_msg("当日无航班（停场/备用，已均分到席位）：" + "、".join(result.idle_tails))

    def _summary_html(self, s1, s2, result) -> str:
        def card(seat, color, text_color):
            chips = " ".join(
                f"<span style='background:{color}; color:{text_color}; "
                f"padding:1px 6px; border-radius:4px; font-weight:700;'>{t}</span>"
                for t in seat.tails
            )
            return (
                f"<td style='vertical-align:top; padding:8px 14px; "
                f"border:1px solid {color}; border-radius:8px;'>"
                f"<div style='color:{color}; font-size:15px; font-weight:700; margin-bottom:4px;'>{seat.name}</div>"
                f"<div style='color:#9fb6cc; font-size:12px; margin-bottom:6px;'>"
                f"飞机 {len(seat.tails)} · 航班 {seat.n_flights} · "
                f"时段A {seat.n_seg_a} · 时段B {seat.n_seg_b} · "
                f"C类 {seat.n_c_class} · B类 {seat.n_b_class} · "
                f"长沙出港 {seat.n_changsha_dep} · 讲解量 {seat.n_briefing} · "
                f"空任务 {seat.n_idle_aircraft}</div>"
                f"<div style='line-height:1.9;'>{chips}</div></td>"
            )

        metrics = " · ".join(f"{k} {v}" for k, v in result.metrics.items())
        return (
            f"<table style='width:100%; border-spacing:10px;'><tr>"
            f"{card(s1, SEAT1_COLOR, '#2b2f33')}"
            f"{card(s2, SEAT2_COLOR, '#143a5c')}"
            f"</tr></table>"
            f"<div style='color:#6d93b2; font-size:11px; margin-top:6px;'>均衡指标（越小越均衡）：{metrics}</div>"
        )

    def _fill_table(self, result):
        by_tail = {ac.tail: ac for ac in result.aircrafts}
        self.table.setRowCount(0)
        for seat, color in ((result.seat1, SEAT1_COLOR), (result.seat2, SEAT2_COLOR)):
            for tail in seat.tails:
                ac = by_tail.get(tail)
                if ac is None:
                    continue
                a, b = ac.n_segment(
                    result.config.split_minutes,
                    result.config.segment_start_minutes,
                    result.config.segment_end_minutes,
                    result.config.service_date,
                )
                ov = ac.overnight_dest
                legs = " ; ".join(
                    f"{f.dep_hhmm} {airport_name(f.dep_icao)}→{airport_name(f.arr_icao)}"
                    for f in ac.flights
                )
                values = [
                    seat.name, ac.tail, ac.ac_type, str(ac.n_flights),
                    "是" if ac.n_flights == 0 else "",
                    str(a), str(b), str(ac.n_c_class), str(ac.n_b_class),
                    str(ac.n_changsha_dep), str(ac.n_briefing),
                    airport_name(ov) if ov else "", legs if ac.n_flights else "空任务/停场/备用",
                ]
                r = self.table.rowCount()
                self.table.insertRow(r)
                for c, val in enumerate(values):
                    item = QTableWidgetItem(val)
                    item.setBackground(QColor(color))
                    item.setForeground(QColor("#1a1a1a"))
                    if c != len(values) - 1:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(r, c, item)

    def _export_excel(self):
        if self.result is None:
            return
        default_name = (
            f"带班分飞机_{self.date.strftime('%m%d') if self.date else '结果'}_{APP_VERSION}.xlsx"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分配结果", default_name, "Excel 文件 (*.xlsx)"
        )
        if not path:
            return
        try:
            write_allocation_excel(self.result, path)
            self._log_msg(f"✓ 已导出：{path}")
            QMessageBox.information(self, "完成", f"已导出到：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))
