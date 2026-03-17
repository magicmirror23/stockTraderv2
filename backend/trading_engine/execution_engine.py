"""Shared execution helpers that refresh account state before every trade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.trading_engine.account_state import (
    AccountState,
    TradeValidationResult,
    ValidationRules,
    fetch_paper_account_state,
    fetch_real_account_state,
    validate_trade_against_account_state,
)


@dataclass(slots=True)
class ExecutionContext:
    accepted: bool
    status: str
    reason: str | None
    validation: TradeValidationResult
    account_state_before: AccountState
    account_state_after: AccountState
    broker_result: dict[str, Any] | None = None


class AccountStateExecutionEngine:
    """Centralizes pre/post refresh and validation for trade execution."""

    def __init__(self, validation_rules: ValidationRules | None = None) -> None:
        self.validation_rules = validation_rules or ValidationRules()

    def execute_with_adapter(
        self,
        adapter: Any,
        order_intent: Mapping[str, Any],
        current_price: float,
    ) -> ExecutionContext:
        before_state = fetch_real_account_state(adapter)
        validation = validate_trade_against_account_state(
            order_intent,
            before_state,
            current_price=current_price,
            rules=self.validation_rules,
        )
        if not validation.allowed:
            return ExecutionContext(
                accepted=False,
                status="rejected",
                reason=validation.reason,
                validation=validation,
                account_state_before=before_state,
                account_state_after=before_state,
                broker_result=None,
            )

        try:
            broker_result = adapter.place_order({**dict(order_intent), "current_price": current_price})
        except Exception as exc:
            return ExecutionContext(
                accepted=False,
                status="error",
                reason=str(exc),
                validation=validation,
                account_state_before=before_state,
                account_state_after=before_state,
                broker_result={"status": "error", "detail": str(exc)},
            )
        status = str(broker_result.get("status") or "unknown").lower()
        accepted = status not in {"failed", "rejected", "error"}
        after_state = fetch_real_account_state(adapter)
        return ExecutionContext(
            accepted=accepted,
            status=status,
            reason=None if accepted else str(broker_result.get("detail") or "Order execution failed"),
            validation=validation,
            account_state_before=before_state,
            account_state_after=after_state,
            broker_result=broker_result,
        )

    def validate_paper_order(
        self,
        account: Any,
        order_intent: Mapping[str, Any],
        current_price: float,
    ) -> tuple[AccountState, TradeValidationResult]:
        before_state = fetch_paper_account_state(account)
        validation = validate_trade_against_account_state(
            order_intent,
            before_state,
            current_price=current_price,
            rules=self.validation_rules,
        )
        return before_state, validation
