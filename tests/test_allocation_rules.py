from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from core.allocator import allocate, evaluate_split
from core.models import Aircraft, AllocationConfig, Flight
from core.parser import build_aircrafts, resolve_columns


def _sample_dynamic_list() -> pd.DataFrame:
    rows = []
    active_tails = [
        "305L",
        "306C",
        "300Z",
        "302Y",
        "303M",
        "30A2",
        "30AM",
        "30AN",
        "30EH",
        "321U",
        "322C",
        "325Q",
        "32Q6",
    ]
    for i, tail in enumerate(active_tails):
        arr = "ZPLJ" if i < 4 else ("ZPPP" if i < 7 else "ZSNJ")
        dep = "ZGHA" if i % 2 == 0 else "ZPPP"
        rows.append(
            {
                "机号": tail,
                "机型": "A320",
                "始发": dep,
                "到达": arr,
                "局飞": datetime(2026, 6, 9, 8 + i % 8, (i * 7) % 60),
                "局达": datetime(2026, 6, 9, 10 + i % 8, (i * 7) % 60),
            }
        )
    return pd.DataFrame(rows)


def _enumerate_assignments(n: int):
    for mask in range(0, 1 << (n - 1)):
        assignment = [0] * n
        for bit in range(n - 1):
            if mask & (1 << bit):
                assignment[bit + 1] = 1
        yield assignment


def _segment_key(metrics: dict) -> tuple[int, int, int, int]:
    a = int(metrics["时段A差"])
    b = int(metrics["时段B差"])
    return max(a, b), a + b, a, b


def _flight(tail: str, dep_time: datetime | None) -> Flight:
    return Flight(
        tail=tail,
        ac_type="A320",
        dep_icao="ZGHA",
        arr_icao="ZSNJ",
        dep_time=dep_time,
        arr_time=dep_time,
    )


class AllocationRuleTests(unittest.TestCase):
    def test_segment_boundaries_exclude_before_0800_and_after_2400(self) -> None:
        cfg = AllocationConfig.for_date(datetime(2026, 6, 29, 0, 0))
        ac = Aircraft(
            tail="T01",
            ac_type="A320",
            flights=[
                _flight("T01", None),
                _flight("T01", datetime(2026, 6, 29, 7, 59)),
                _flight("T01", datetime(2026, 6, 29, 8, 0)),
                _flight("T01", datetime(2026, 6, 29, 8, 1)),
                _flight("T01", datetime(2026, 6, 29, 13, 30)),
                _flight("T01", datetime(2026, 6, 29, 13, 31)),
                _flight("T01", datetime(2026, 6, 29, 23, 59)),
                _flight("T01", datetime(2026, 6, 30, 0, 0)),
                _flight("T01", datetime(2026, 6, 30, 0, 1)),
            ],
        )

        self.assertEqual(
            ac.n_segment(
                cfg.split_minutes,
                cfg.segment_start_minutes,
                cfg.segment_end_minutes,
                cfg.service_date,
            ),
            (2, 3),
        )

    def test_segment_balance_is_global_first_priority(self) -> None:
        rows = []
        specs = [
            ("T01", [datetime(2026, 6, 29, 8, 10), datetime(2026, 6, 29, 8, 50)]),
            ("T02", [datetime(2026, 6, 29, 9, 10), datetime(2026, 6, 29, 9, 50)]),
            ("T03", [datetime(2026, 6, 29, 10, 10)]),
            ("T04", [datetime(2026, 6, 29, 14, 10), datetime(2026, 6, 29, 14, 50)]),
            ("T05", [datetime(2026, 6, 29, 15, 10), datetime(2026, 6, 29, 15, 50)]),
            ("T06", [datetime(2026, 6, 29, 16, 10)]),
        ]
        for tail, deps in specs:
            for dep_time in deps:
                rows.append(
                    {
                        "机号": tail,
                        "机型": "A320",
                        "始发": "ZGHA",
                        "到达": "ZSNJ",
                        "局飞": dep_time,
                        "局达": dep_time,
                    }
                )
        df = pd.DataFrame(rows)
        aircrafts = build_aircrafts(df, resolve_columns(list(df.columns)), known_tails=())
        cfg = AllocationConfig.for_date(datetime(2026, 6, 29, 0, 0))

        best_segment_key = min(
            _segment_key(evaluate_split(aircrafts, assignment, cfg)[1])
            for assignment in _enumerate_assignments(len(aircrafts))
        )
        result = allocate(aircrafts, cfg)

        self.assertEqual(_segment_key(result.metrics), best_segment_key)

    def test_known_fleet_is_completed_and_idle_aircraft_are_split(self) -> None:
        df = _sample_dynamic_list()
        aircrafts = build_aircrafts(df, resolve_columns(list(df.columns)))
        result = allocate(aircrafts, AllocationConfig())

        self.assertEqual(len(aircrafts), 17)
        self.assertEqual(result.idle_tails, ["8432", "8983", "8285", "8318"])
        self.assertEqual(result.seat1.n_idle_aircraft, 2)
        self.assertEqual(result.seat2.n_idle_aircraft, 2)
        self.assertEqual(result.metrics["空任务飞机差"], 0)

    def test_blank_task_row_does_not_create_fake_flight(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "机号": "305L",
                    "机型": "A320",
                    "始发": "",
                    "到达": "",
                    "局飞": None,
                    "局达": None,
                }
            ]
        )
        aircrafts = build_aircrafts(df, resolve_columns(list(df.columns)), known_tails=("305L",))
        self.assertEqual(len(aircrafts), 1)
        self.assertEqual(aircrafts[0].tail, "305L")
        self.assertEqual(aircrafts[0].n_flights, 0)

    def test_registration_prefix_does_not_duplicate_known_aircraft(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "机号": "B-30AM",
                    "机型": "A320N",
                    "始发": "ZGHA",
                    "到达": "ZSNJ",
                    "局飞": datetime(2026, 6, 9, 10, 0),
                    "局达": datetime(2026, 6, 9, 12, 0),
                },
                {
                    "机号": "B-30AN",
                    "机型": "A320N",
                    "始发": "ZSNJ",
                    "到达": "ZGHA",
                    "局飞": datetime(2026, 6, 9, 20, 0),
                    "局达": datetime(2026, 6, 9, 22, 0),
                },
            ]
        )
        aircrafts = build_aircrafts(df, resolve_columns(list(df.columns)))
        by_tail = {ac.tail: ac for ac in aircrafts}

        self.assertEqual(len(aircrafts), 17)
        self.assertEqual(by_tail["30AM"].n_flights, 1)
        self.assertEqual(by_tail["30AN"].n_flights, 1)
        self.assertNotIn("B-30AM", by_tail)
        self.assertNotIn("B-30AN", by_tail)

    def test_aircraft_tail_display_uses_explicit_registration_format(self) -> None:
        # 页面显示层约定：内部短机号保持 30AM，展示时带 B- 前缀，
        # 让英文后缀不会被截图/OCR 误判成中文。
        self.assertEqual("B-30AM", f"B-{'30AM'}")
        self.assertEqual("B-30AN", f"B-{'30AN'}")

    def test_cb_destination_changsha_and_briefing_metrics_are_active(self) -> None:
        df = _sample_dynamic_list()
        aircrafts = build_aircrafts(df, resolve_columns(list(df.columns)))
        result = allocate(aircrafts, AllocationConfig())
        by_tail = {ac.tail: ac for ac in result.aircrafts}

        def seat_dest_count(seat, dest: str) -> int:
            return sum(
                1
                for tail in seat.tails
                for flight in by_tail[tail].flights
                if flight.arr_icao == dest
            )

        self.assertLessEqual(
            abs(seat_dest_count(result.seat1, "ZPLJ") - seat_dest_count(result.seat2, "ZPLJ")),
            1,
        )
        self.assertIn("C类同目的地差", result.metrics)
        self.assertIn("B类同目的地差", result.metrics)
        self.assertIn("长沙出港差", result.metrics)
        self.assertIn("讲解量差", result.metrics)
        self.assertLessEqual(abs(result.seat1.n_briefing - result.seat2.n_briefing), 1)

    def test_same_overnight_destination_close_landings_are_split(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "机号": "T01",
                    "机型": "A320",
                    "始发": "ZPPP",
                    "到达": "ZGHA",
                    "局飞": datetime(2026, 6, 9, 18, 0),
                    "局达": datetime(2026, 6, 9, 20, 0),
                },
                {
                    "机号": "T02",
                    "机型": "A320",
                    "始发": "ZPPP",
                    "到达": "ZGHA",
                    "局飞": datetime(2026, 6, 9, 18, 40),
                    "局达": datetime(2026, 6, 9, 20, 40),
                },
                {
                    "机号": "T03",
                    "机型": "A320",
                    "始发": "ZPPP",
                    "到达": "ZGHA",
                    "局飞": datetime(2026, 6, 9, 21, 10),
                    "局达": datetime(2026, 6, 9, 23, 10),
                },
                {
                    "机号": "T04",
                    "机型": "A320",
                    "始发": "ZPPP",
                    "到达": "ZGHA",
                    "局飞": datetime(2026, 6, 9, 21, 50),
                    "局达": datetime(2026, 6, 9, 23, 50),
                },
            ]
        )
        aircrafts = build_aircrafts(df, resolve_columns(list(df.columns)), known_tails=())

        clustered_score, clustered_metrics = evaluate_split(aircrafts, [0, 0, 1, 1], AllocationConfig())
        split_score, split_metrics = evaluate_split(aircrafts, [0, 1, 0, 1], AllocationConfig())

        self.assertEqual(clustered_metrics["过夜落地窗口冲突"], 2)
        self.assertEqual(split_metrics["过夜落地窗口冲突"], 0)
        self.assertLess(split_score, clustered_score)

        result = allocate(aircrafts, AllocationConfig())
        self.assertEqual(result.metrics["过夜落地窗口冲突"], 0)


if __name__ == "__main__":
    unittest.main()
