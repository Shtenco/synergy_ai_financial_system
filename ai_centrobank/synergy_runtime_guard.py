#!/usr/bin/env python3
"""Fail-closed runtime guard for the SYNERGY RL agent.

The guard owns the run budget and safety state. It is intentionally independent
from the RL policy: the policy may propose actions, but it cannot raise limits,
change the signer, bypass chain checks, or suppress the emergency stop.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import json
import time


MAINNET_ARM_PHRASE = "I_ACCEPT_MAX_20_POL_LOSS_FOR_150_BLOCKS"
AMOY_CHAIN_ID = 80002
POLYGON_CHAIN_ID = 137


class SafetyViolation(RuntimeError):
    """Raised when a hard runtime invariant is violated."""


@dataclass(frozen=True)
class GuardConfig:
    network: str
    chain_id: int
    execution_mode: str
    tx_submission_mode: str
    block_limit: int = 150
    action_interval: int = 10
    max_loss_pol: Decimal = Decimal("20")
    min_owner_pol: Decimal = Decimal("10")
    refill_pol: Decimal = Decimal("2")
    max_single_tx_gas_pol: Decimal = Decimal("0.25")
    max_single_action_notional_pol: Decimal = Decimal("2")
    stop_file: Path = Path("runtime/synergy_agent/STOP")
    private_tx_endpoint: str = ""
    mainnet_arm_phrase: str = "DISABLED"

    def validate_static(self) -> None:
        if self.chain_id not in {AMOY_CHAIN_ID, POLYGON_CHAIN_ID}:
            raise SafetyViolation(f"unsupported chain_id={self.chain_id}")
        if self.network == "amoy" and self.chain_id != AMOY_CHAIN_ID:
            raise SafetyViolation("Amoy must use chain ID 80002")
        if self.network == "polygon" and self.chain_id != POLYGON_CHAIN_ID:
            raise SafetyViolation("Polygon mainnet must use chain ID 137")
        if self.execution_mode not in {"dry-run", "execute"}:
            raise SafetyViolation("EXECUTION_MODE must be dry-run or execute")
        if self.block_limit != 150:
            raise SafetyViolation("BLOCK_LIMIT is hard-pinned to 150")
        if self.action_interval != 10:
            raise SafetyViolation("ACTION_INTERVAL is hard-pinned to 10")
        if self.max_loss_pol != Decimal("20"):
            raise SafetyViolation("MAX_LOSS_POL is hard-pinned to 20")
        if self.min_owner_pol < Decimal("10"):
            raise SafetyViolation("MIN_OWNER_POL cannot be below 10")
        if self.refill_pol != Decimal("2"):
            raise SafetyViolation("REFILL_POL is hard-pinned to 2")
        if self.max_single_tx_gas_pol <= 0 or self.max_single_tx_gas_pol > Decimal("0.25"):
            raise SafetyViolation("MAX_SINGLE_TX_GAS_POL must be in (0, 0.25]")
        if self.max_single_action_notional_pol <= 0 or self.max_single_action_notional_pol > Decimal("5"):
            raise SafetyViolation("MAX_SINGLE_ACTION_NOTIONAL_POL must be in (0, 5]")
        if self.network == "polygon" and self.execution_mode == "execute":
            if self.mainnet_arm_phrase != MAINNET_ARM_PHRASE:
                raise SafetyViolation("mainnet arm phrase is absent or incorrect")
            if self.tx_submission_mode != "private":
                raise SafetyViolation("mainnet execution requires private submission")
            if not self.private_tx_endpoint.startswith("https://"):
                raise SafetyViolation("mainnet requires an HTTPS private transaction endpoint")


@dataclass
class RiskLedger:
    start_block: int
    start_nav_pol: Decimal
    current_nav_pol: Decimal
    cumulative_gas_pol: Decimal = Decimal("0")
    realized_loss_pol: Decimal = Decimal("0")
    refill_count: int = 0
    actions_attempted: int = 0
    actions_executed: int = 0
    last_block: int = 0
    halted: bool = False
    halt_reason: str = ""

    @property
    def mark_to_market_loss_pol(self) -> Decimal:
        return max(Decimal("0"), self.start_nav_pol - self.current_nav_pol)

    @property
    def total_loss_pol(self) -> Decimal:
        # Gas is normally reflected in wallet NAV. Use the maximum rather than
        # double-counting it, while keeping explicit gas diagnostics.
        return max(self.mark_to_market_loss_pol, self.realized_loss_pol)

    def to_json(self) -> Dict[str, Any]:
        result = asdict(self)
        for key, value in list(result.items()):
            if isinstance(value, Decimal):
                result[key] = str(value)
        return result


class RuntimeGuard:
    def __init__(self, config: GuardConfig, ledger: RiskLedger) -> None:
        config.validate_static()
        self.config = config
        self.ledger = ledger

    def assert_chain(self, observed_chain_id: int) -> None:
        if observed_chain_id != self.config.chain_id:
            raise SafetyViolation(
                f"RPC chain mismatch: expected {self.config.chain_id}, got {observed_chain_id}"
            )

    def assert_signer(self, observed_address: str, expected_address: str) -> None:
        if observed_address.lower() != expected_address.lower():
            raise SafetyViolation("private key does not match EXPECTED_SIGNER_ADDRESS")

    def check_stop_file(self) -> None:
        if self.config.stop_file.exists():
            self.halt("emergency STOP file present")
            raise SafetyViolation(self.ledger.halt_reason)

    def blocks_elapsed(self, current_block: int) -> int:
        return max(0, current_block - self.ledger.start_block)

    def should_stop(self, current_block: int) -> bool:
        self.ledger.last_block = current_block
        if self.ledger.halted:
            return True
        if self.blocks_elapsed(current_block) >= self.config.block_limit:
            self.halt("150-block limit reached")
            return True
        if self.ledger.total_loss_pol >= self.config.max_loss_pol:
            self.halt("20 POL hard loss limit reached")
            return True
        return False

    def should_act(self, current_block: int) -> bool:
        return (
            not self.should_stop(current_block)
            and self.blocks_elapsed(current_block) % self.config.action_interval == 0
        )

    def update_nav(self, nav_pol: Decimal) -> None:
        if not nav_pol.is_finite() or nav_pol < 0:
            raise SafetyViolation("invalid NAV observation")
        self.ledger.current_nav_pol = nav_pol
        if self.ledger.total_loss_pol >= self.config.max_loss_pol:
            self.halt("20 POL hard loss limit reached")

    def register_gas(self, gas_pol: Decimal) -> None:
        if not gas_pol.is_finite() or gas_pol < 0:
            raise SafetyViolation("invalid gas amount")
        if gas_pol > self.config.max_single_tx_gas_pol:
            self.halt("single transaction gas cap exceeded")
            raise SafetyViolation(self.ledger.halt_reason)
        self.ledger.cumulative_gas_pol += gas_pol

    def validate_action_notional(self, notional_pol: Decimal) -> None:
        if not notional_pol.is_finite() or notional_pol < 0:
            raise SafetyViolation("invalid action notional")
        if notional_pol > self.config.max_single_action_notional_pol:
            raise SafetyViolation("single action notional cap exceeded")

    def needs_refill(self, owner_pol: Decimal) -> bool:
        if not owner_pol.is_finite() or owner_pol < 0:
            raise SafetyViolation("invalid owner POL balance")
        return owner_pol < self.config.min_owner_pol

    def refill_target(self) -> Decimal:
        return self.config.refill_pol

    def register_refill(self, received_pol: Decimal) -> None:
        if received_pol < self.config.refill_pol:
            raise SafetyViolation("gas refill returned less than 2 POL")
        self.ledger.refill_count += 1

    def halt(self, reason: str) -> None:
        self.ledger.halted = True
        self.ledger.halt_reason = reason

    def write_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.ledger.to_json(), indent=2), encoding="utf-8")
        tmp.replace(path)


class GuardedLoop:
    """Chain-agnostic monitored loop.

    Callbacks are injected by a concrete Web3/contract adapter. This keeps safety
    logic independently testable and prevents the RL model from signing directly.
    """

    def __init__(
        self,
        guard: RuntimeGuard,
        get_block: Callable[[], int],
        get_owner_pol: Callable[[], Decimal],
        get_nav_pol: Callable[[], Decimal],
        learn_one_block: Callable[[int], None],
        propose_action: Callable[[int], Dict[str, Any]],
        execute_action: Callable[[Dict[str, Any]], Dict[str, Decimal]],
        refill_gas: Callable[[Decimal], Decimal],
        state_path: Path,
        poll_seconds: float = 2.0,
    ) -> None:
        self.guard = guard
        self.get_block = get_block
        self.get_owner_pol = get_owner_pol
        self.get_nav_pol = get_nav_pol
        self.learn_one_block = learn_one_block
        self.propose_action = propose_action
        self.execute_action = execute_action
        self.refill_gas = refill_gas
        self.state_path = state_path
        self.poll_seconds = poll_seconds

    def run(self) -> RiskLedger:
        seen_block: Optional[int] = None
        while True:
            self.guard.check_stop_file()
            block = self.get_block()
            if seen_block == block:
                time.sleep(self.poll_seconds)
                continue
            seen_block = block
            self.guard.update_nav(self.get_nav_pol())
            self.guard.write_state(self.state_path)
            if self.guard.should_stop(block):
                break

            # The agent learns from every observed block.
            self.learn_one_block(block)

            owner_pol = self.get_owner_pol()
            if self.guard.needs_refill(owner_pol):
                received = self.refill_gas(self.guard.refill_target())
                self.guard.register_refill(received)
                self.guard.update_nav(self.get_nav_pol())
                self.guard.write_state(self.state_path)
                if self.guard.should_stop(block):
                    break

            if not self.guard.should_act(block):
                continue

            action = self.propose_action(block)
            notional = Decimal(str(action.get("notional_pol", "0")))
            self.guard.validate_action_notional(notional)
            self.guard.ledger.actions_attempted += 1
            if self.guard.config.execution_mode == "dry-run":
                continue

            result = self.execute_action(action)
            gas = Decimal(str(result.get("gas_pol", "0")))
            self.guard.register_gas(gas)
            self.guard.ledger.actions_executed += 1
            self.guard.update_nav(self.get_nav_pol())
            self.guard.write_state(self.state_path)

        self.guard.write_state(self.state_path)
        return self.guard.ledger
