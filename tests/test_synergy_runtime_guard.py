from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ai_centrobank.synergy_runtime_guard import (
    GuardConfig,
    RiskLedger,
    RuntimeGuard,
    SafetyViolation,
)


class RuntimeGuardTests(unittest.TestCase):
    def make_guard(self, **overrides):
        values = dict(
            network="amoy",
            chain_id=80002,
            execution_mode="dry-run",
            tx_submission_mode="commit-reveal",
            block_limit=150,
            action_interval=10,
            max_loss_pol=Decimal("20"),
            min_owner_pol=Decimal("10"),
            refill_pol=Decimal("2"),
            max_single_tx_gas_pol=Decimal("0.25"),
            max_single_action_notional_pol=Decimal("5"),
        )
        values.update(overrides)
        config = GuardConfig(**values)
        ledger = RiskLedger(1_000, Decimal("100"), Decimal("100"), last_block=1_000)
        return RuntimeGuard(config, ledger)

    def test_hard_150_block_stop(self):
        guard = self.make_guard()
        self.assertFalse(guard.should_stop(1_149))
        self.assertTrue(guard.should_stop(1_150))
        self.assertEqual(guard.ledger.halt_reason, "150-block limit reached")

    def test_hard_20_pol_loss_stop(self):
        guard = self.make_guard()
        guard.update_nav(Decimal("80"))
        self.assertTrue(guard.should_stop(1_010))
        self.assertEqual(guard.ledger.total_loss_pol, Decimal("20"))

    def test_action_only_every_ten_blocks(self):
        guard = self.make_guard()
        self.assertTrue(guard.should_act(1_010))
        self.assertFalse(guard.should_act(1_011))

    def test_refill_rule_is_exactly_two_pol(self):
        guard = self.make_guard()
        self.assertTrue(guard.needs_refill(Decimal("9.999")))
        self.assertEqual(guard.refill_target(), Decimal("2"))
        with self.assertRaises(SafetyViolation):
            guard.register_refill(Decimal("1.99"))
        guard.register_refill(Decimal("2"))
        self.assertEqual(guard.ledger.refill_count, 1)

    def test_mainnet_execute_requires_private_endpoint_and_arm_phrase(self):
        with self.assertRaises(SafetyViolation):
            self.make_guard(
                network="polygon",
                chain_id=137,
                execution_mode="execute",
                tx_submission_mode="public",
            )

    def test_wrong_chain_rejected(self):
        guard = self.make_guard()
        with self.assertRaises(SafetyViolation):
            guard.assert_chain(137)

    def test_single_transaction_gas_cap(self):
        guard = self.make_guard()
        with self.assertRaises(SafetyViolation):
            guard.register_gas(Decimal("0.251"))

    def test_emergency_stop_file(self):
        with tempfile.TemporaryDirectory() as td:
            stop = Path(td) / "STOP"
            stop.write_text("stop", encoding="utf-8")
            guard = self.make_guard(stop_file=stop)
            with self.assertRaises(SafetyViolation):
                guard.check_stop_file()
            self.assertTrue(guard.ledger.halted)


if __name__ == "__main__":
    unittest.main()
