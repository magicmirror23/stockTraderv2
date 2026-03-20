"""Option contract selection, pricing, and validation helpers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.trading_engine.account_state import instrument_key


def days_to_expiry(expiry: str) -> int:
    try:
        expiry_date = date.fromisoformat(expiry)
    except ValueError:
        return 1
    return max((expiry_date - date.today()).days, 0)


def expiry_after(days: int) -> str:
    return (date.today() + timedelta(days=max(days, 1))).isoformat()


def strike_step_for_underlying(ticker: str, spot: float) -> float:
    symbol = str(ticker or "").upper()
    if symbol == "BANKNIFTY":
        return 100.0
    if symbol == "NIFTY50":
        return 50.0
    if spot >= 5000:
        return 100.0
    if spot >= 1000:
        return 50.0
    if spot >= 200:
        return 10.0
    return 5.0


def atm_strike(spot: float, step: float) -> float:
    if spot <= 0 or step <= 0:
        return 0.0
    return round(spot / step) * step


def estimate_option_premium(
    *,
    spot: float,
    strike: float,
    option_type: str,
    days_to_expiry: int,
    confidence: float,
    expected_return: float,
) -> float:
    if spot <= 0 or strike <= 0:
        return 0.0
    option_type = str(option_type or "").upper()
    intrinsic = max(spot - strike, 0.0) if option_type == "CE" else max(strike - spot, 0.0)
    days_factor = max(days_to_expiry, 1) / 7.0
    moneyness = abs(spot - strike) / max(spot, 1.0)
    confidence_boost = 0.8 + max(min(confidence, 1.0), 0.0)
    move_boost = 1.0 + min(abs(expected_return) * 6.0, 1.5)
    time_value = spot * 0.012 * math.sqrt(days_factor) * confidence_boost * move_boost * max(0.25, 1.0 - moneyness)
    premium = intrinsic + max(time_value, spot * 0.002)
    return round(max(premium, 1.0), 2)


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def estimate_option_greeks(
    *,
    spot: float,
    strike: float,
    days_to_expiry: int,
    option_type: str,
    implied_volatility: float | None = None,
    risk_free_rate: float = 0.06,
) -> dict[str, float]:
    """Approximate Black-Scholes Greeks for monitoring and validation."""

    if spot <= 0 or strike <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0, "iv": 0.0}

    time_to_expiry = max(days_to_expiry, 1) / 365.0
    sigma = max(implied_volatility or 0.22, 0.05)
    root_t = math.sqrt(time_to_expiry)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * time_to_expiry) / max(sigma * root_t, 1e-9)
    d2 = d1 - sigma * root_t
    option_type = str(option_type or "").upper()

    if option_type == "CE":
        delta = _norm_cdf(d1)
        theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * root_t) - risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(d2)) / 365.0
        rho = strike * time_to_expiry * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(d2) / 100.0
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * root_t) + risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(-d2)) / 365.0
        rho = -strike * time_to_expiry * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(-d2) / 100.0

    gamma = _norm_pdf(d1) / max(spot * sigma * root_t, 1e-9)
    vega = (spot * _norm_pdf(d1) * root_t) / 100.0
    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
        "iv": round(sigma, 4),
    }


@dataclass(slots=True)
class ResolvedOptionContract:
    ticker: str
    option_type: str
    strike: float
    expiry: str
    premium: float
    underlying_spot: float
    days_to_expiry: int
    contract_key: str
    contract_label: str
    tradingsymbol: str | None = None
    symbol_token: str | None = None
    exchange: str = "NFO"
    product_type: str = "INTRADAY"
    resolution_source: str = "synthetic"
    live_trade_ready: bool = False
    validation_issues: list[str] = field(default_factory=list)
    greeks: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class OptionContractResolver:
    """Resolve option contracts in a broker-safe, paper-friendly way."""

    _underlying_aliases = {
        "NIFTY50": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "SENSEX": "SENSEX",
    }

    def resolve_for_signal(
        self,
        *,
        ticker: str,
        action: str,
        confidence: float,
        expected_return: float,
        spot: float,
        expiry_days: int,
        strike_steps_from_atm: int = 0,
        min_days_to_expiry: int = 0,
        option_bias: str = "both",
        adapter: Any | None = None,
    ) -> ResolvedOptionContract | None:
        if action not in {"buy", "sell"} or spot <= 0:
            return None

        option_type = "CE" if action == "buy" else "PE"
        if option_bias == "calls_only" and option_type != "CE":
            return None
        if option_bias == "puts_only" and option_type != "PE":
            return None

        step = strike_step_for_underlying(ticker, spot)
        atm = atm_strike(spot, step)
        if option_type == "CE":
            strike = atm + (max(strike_steps_from_atm, 0) * step)
        else:
            strike = max(step, atm - (max(strike_steps_from_atm, 0) * step))

        actual_expiry_days = max(expiry_days, min_days_to_expiry or 0, 1)
        expiry = expiry_after(actual_expiry_days)
        premium = estimate_option_premium(
            spot=spot,
            strike=strike,
            option_type=option_type,
            days_to_expiry=actual_expiry_days,
            confidence=confidence,
            expected_return=expected_return,
        )

        contract = ResolvedOptionContract(
            ticker=str(ticker).upper(),
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            premium=premium,
            underlying_spot=spot,
            days_to_expiry=days_to_expiry(expiry),
            contract_key=instrument_key(ticker, option_type, strike, expiry),
            contract_label=f"{str(ticker).upper()} {expiry} {int(strike) if float(strike).is_integer() else strike} {option_type}",
            greeks=estimate_option_greeks(
                spot=spot,
                strike=strike,
                days_to_expiry=actual_expiry_days,
                option_type=option_type,
            ),
        )

        self._validate_contract(contract)
        if adapter is not None:
            self._enrich_with_broker_mapping(contract, adapter)
        return contract

    def _validate_contract(self, contract: ResolvedOptionContract) -> None:
        issues: list[str] = []
        if contract.premium <= 0:
            issues.append("Estimated premium is unavailable.")
        if contract.days_to_expiry <= 0:
            issues.append("Contract expiry is invalid or already passed.")
        if contract.option_type not in {"CE", "PE"}:
            issues.append("Option type must be CE or PE.")
        if contract.underlying_spot <= 0:
            issues.append("Underlying spot price is unavailable.")
        contract.validation_issues = issues
        contract.live_trade_ready = not issues and bool(contract.tradingsymbol and contract.symbol_token)

    def _enrich_with_broker_mapping(self, contract: ResolvedOptionContract, adapter: Any) -> None:
        search_method = getattr(adapter, "search_instruments", None)
        if not callable(search_method):
            contract.validation_issues.append("Broker search capability is unavailable.")
            contract.live_trade_ready = False
            return

        search_symbol = self._underlying_aliases.get(contract.ticker, contract.ticker)
        strike_text = f"{contract.strike:g}"
        expiry_date = date.fromisoformat(contract.expiry)
        expiry_variants = {
            expiry_date.strftime("%d%b%y").upper(),
            expiry_date.strftime("%d%b%Y").upper(),
            expiry_date.strftime("%b").upper(),
        }
        queries = [
            f"{search_symbol} {variant} {strike_text} {contract.option_type}"
            for variant in expiry_variants
        ]
        queries.extend(
            [
                f"{search_symbol} {strike_text} {contract.option_type}",
                f"{search_symbol} {contract.option_type} {strike_text}",
            ]
        )

        best_match: dict[str, Any] | None = None
        best_score = -1
        for query in queries:
            try:
                results = search_method("NFO", query) or []
            except Exception:
                continue
            for item in results:
                score = self._score_candidate(item, contract, search_symbol, strike_text, expiry_variants)
                if score > best_score:
                    best_match = item
                    best_score = score

        if best_match and best_score >= 8:
            contract.tradingsymbol = str(best_match.get("tradingsymbol") or "").upper() or None
            contract.symbol_token = str(
                best_match.get("symboltoken")
                or best_match.get("symbolToken")
                or ""
            ) or None
            contract.exchange = str(best_match.get("exchange") or "NFO").upper()
            contract.resolution_source = "broker_search"
        else:
            contract.validation_issues.append("Broker symbol/token resolution did not find a confident contract match.")

        contract.live_trade_ready = not contract.validation_issues and bool(contract.tradingsymbol and contract.symbol_token)

    def _score_candidate(
        self,
        item: dict[str, Any],
        contract: ResolvedOptionContract,
        search_symbol: str,
        strike_text: str,
        expiry_variants: set[str],
    ) -> int:
        symbol = str(item.get("tradingsymbol") or item.get("symbol") or "").upper()
        if not symbol:
            return -1

        score = 0
        if search_symbol in symbol:
            score += 4
        if contract.option_type in symbol:
            score += 3
        if strike_text.replace(".0", "") in symbol:
            score += 3
        if any(expiry in symbol for expiry in expiry_variants):
            score += 4
        if str(item.get("exchange") or "").upper() == "NFO":
            score += 2
        if item.get("symboltoken") or item.get("symbolToken"):
            score += 2
        return score
