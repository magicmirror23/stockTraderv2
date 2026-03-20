"""Shared execution helpers that refresh account state before every trade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.services.audit_service import record_audit_event
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
    risk_decision: Any | None = None


class AccountStateExecutionEngine:
    """Centralizes pre/post refresh and validation for trade execution."""

    def __init__(self, validation_rules: ValidationRules | None = None) -> None:
        self.validation_rules = validation_rules or ValidationRules()

    def execute_with_adapter(
        self,
        adapter: Any,
        order_intent: Mapping[str, Any],
        current_price: float,
        *,
        risk_manager: Any | None = None,
        expected_return_pct: float | None = None,
        stop_loss_pct: float | None = None,
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
                risk_decision=None,
            )

        risk_decision = None
        if risk_manager is not None:
            risk_manager.sync_account_state(before_state)
            risk_decision = risk_manager.validate_order(
                order_intent,
                before_state,
                current_price=current_price,
                expected_return_pct=expected_return_pct,
                stop_loss_pct=stop_loss_pct,
            )
            if not risk_decision.allowed:
                record_audit_event(
                    "RISK_CHECK_FAILED",
                    entity_type="order",
                    entity_id=str(order_intent.get("ticker") or ""),
                    data={
                        "order_intent": dict(order_intent),
                        "decision": risk_decision.to_dict(),
                    },
                    source="execution_engine",
                )
                return ExecutionContext(
                    accepted=False,
                    status="rejected",
                    reason=risk_decision.reason,
                    validation=validation,
                    account_state_before=before_state,
                    account_state_after=before_state,
                    broker_result=None,
                    risk_decision=risk_decision,
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
                risk_decision=risk_decision,
            )
        status = str(broker_result.get("status") or "unknown").lower()
        accepted = status not in {"failed", "rejected", "error"}
        after_state = fetch_real_account_state(adapter)
        if accepted and risk_manager is not None:
            risk_manager.sync_account_state(after_state)
        return ExecutionContext(
            accepted=accepted,
            status=status,
            reason=None if accepted else str(broker_result.get("detail") or "Order execution failed"),
            validation=validation,
            account_state_before=before_state,
            account_state_after=after_state,
            broker_result=broker_result,
            risk_decision=risk_decision,
        )

    def validate_paper_order(
        self,
        account: Any,
        order_intent: Mapping[str, Any],
        current_price: float,
        *,
        risk_manager: Any | None = None,
        expected_return_pct: float | None = None,
        stop_loss_pct: float | None = None,
    ) -> tuple[AccountState, TradeValidationResult, Any | None]:
        before_state = fetch_paper_account_state(account)
        validation = validate_trade_against_account_state(
            order_intent,
            before_state,
            current_price=current_price,
            rules=self.validation_rules,
        )
        risk_decision = None
        if validation.allowed and risk_manager is not None:
            risk_manager.sync_account_state(before_state)
            risk_decision = risk_manager.validate_order(
                order_intent,
                before_state,
                current_price=current_price,
                expected_return_pct=expected_return_pct,
                stop_loss_pct=stop_loss_pct,
            )
            if not risk_decision.allowed:
                record_audit_event(
                    "RISK_CHECK_FAILED",
                    entity_type="paper_order",
                    entity_id=str(order_intent.get("ticker") or ""),
                    data={
                        "order_intent": dict(order_intent),
                        "decision": risk_decision.to_dict(),
                    },
                    source="execution_engine",
                )
                validation = TradeValidationResult(
                    allowed=False,
                    reason=risk_decision.reason,
                    code=risk_decision.code,
                    account_state=before_state,
                    normalized_quantity=int(order_intent.get("quantity") or 0),
                    available_cash=before_state.available_cash,
                    held_quantity=before_state.held_quantity(str(order_intent.get("ticker") or "")),
                )
        return before_state, validation, risk_decision
