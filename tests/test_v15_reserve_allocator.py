import importlib.util
import pathlib
import sys
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "simulation" / "v15" / "reserve_allocator.py"
spec = importlib.util.spec_from_file_location("v15_reserve_allocator", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def assets():
    return [
        m.ReserveAsset("USDC", .98, {"depeg": .70, "crypto": .98}, "stable"),
        m.ReserveAsset("DAI", .92, {"depeg": .75, "crypto": .90}, "stable"),
        m.ReserveAsset("WETH", .85, {"depeg": .85, "crypto": .55}, "crypto"),
    ]


class ReserveAllocatorTests(unittest.TestCase):
    def test_binding_stablecoin_group_limit_prevents_all_profit_from_returning_to_stables(self):
        alloc, heads, rem = m.allocate_retained_surplus(
            20, assets(), {"base": 5, "depeg": 0, "crypto": 10},
            100, {"stable": 70, "crypto": 30}, {"stable": .70, "crypto": .60}, 1
        )
        self.assertGreater(alloc["WETH"], 0)
        final_total = 100 + sum(alloc.values())
        final_stable = 70 + alloc["USDC"] + alloc["DAI"]
        self.assertLessEqual(final_stable / final_total, .70 + 1e-12)
        self.assertEqual(rem, 0)

    def test_allocator_improves_weakest_headroom_when_feasible(self):
        before = min({"base": 5, "depeg": 0, "crypto": 10}.values())
        _, heads, _ = m.allocate_retained_surplus(
            10, assets(), {"base": 5, "depeg": 0, "crypto": 10},
            100, {"stable": 60, "crypto": 40}, {"stable": .75, "crypto": .75}, 1
        )
        self.assertGreater(min(heads.values()), before)

    def test_no_feasible_group_capacity_leaves_budget_unallocated(self):
        only = [m.ReserveAsset("USDC", 1, {"stress": 1}, "stable")]
        alloc, _, rem = m.allocate_retained_surplus(
            5, only, {"base": 0, "stress": 0},
            100, {"stable": 100}, {"stable": .90}, 1
        )
        self.assertEqual(alloc["USDC"], 0)
        self.assertEqual(rem, 5)


if __name__ == "__main__":
    unittest.main()
