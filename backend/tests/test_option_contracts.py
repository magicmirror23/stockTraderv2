from __future__ import annotations

from backend.trading_engine.options_contracts import OptionContractResolver


def test_option_contract_resolver_returns_contract_with_greeks():
    resolver = OptionContractResolver()

    contract = resolver.resolve_for_signal(
        ticker="NIFTY50",
        action="buy",
        confidence=0.78,
        expected_return=0.012,
        spot=22450.0,
        expiry_days=7,
        strike_steps_from_atm=1,
        option_bias="both",
    )

    assert contract is not None
    assert contract.option_type == "CE"
    assert contract.premium > 0
    assert contract.greeks["delta"] > 0
    assert contract.contract_key


def test_option_contract_resolver_uses_broker_search_when_available():
    resolver = OptionContractResolver()

    class FakeAdapter:
        def search_instruments(self, exchange: str, search_text: str) -> list[dict]:
            assert exchange == "NFO"
            assert "NIFTY" in search_text
            return [
                {
                    "exchange": "NFO",
                    "tradingsymbol": "NIFTY27MAR2622500CE",
                    "symboltoken": "12345",
                }
            ]

    contract = resolver.resolve_for_signal(
        ticker="NIFTY50",
        action="buy",
        confidence=0.81,
        expected_return=0.015,
        spot=22450.0,
        expiry_days=8,
        strike_steps_from_atm=1,
        option_bias="both",
        adapter=FakeAdapter(),
    )

    assert contract is not None
    assert contract.tradingsymbol == "NIFTY27MAR2622500CE"
    assert contract.symbol_token == "12345"
    assert contract.live_trade_ready is True
    assert contract.resolution_source == "broker_search"
