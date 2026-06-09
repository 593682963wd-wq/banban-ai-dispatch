from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from core.allocator import allocate
from core.models import AllocationConfig
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


class AllocationRuleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
