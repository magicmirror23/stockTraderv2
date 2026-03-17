"""Company metadata used for ticker-specific news queries."""

from __future__ import annotations

from typing import Iterable


_COMPANY_PROFILES: dict[str, dict[str, list[str] | str]] = {
    "RELIANCE": {"company": "Reliance Industries", "aliases": ["Reliance Industries Ltd", "RIL"]},
    "TCS": {"company": "Tata Consultancy Services", "aliases": ["TCS"]},
    "HDFCBANK": {"company": "HDFC Bank", "aliases": ["HDFC Bank Ltd"]},
    "INFY": {"company": "Infosys", "aliases": ["Infosys Ltd"]},
    "ICICIBANK": {"company": "ICICI Bank", "aliases": ["ICICI Bank Ltd"]},
    "HINDUNILVR": {"company": "Hindustan Unilever", "aliases": ["HUL", "Hindustan Unilever Ltd"]},
    "SBIN": {"company": "State Bank of India", "aliases": ["SBI"]},
    "BHARTIARTL": {"company": "Bharti Airtel", "aliases": ["Airtel", "Bharti Airtel Ltd"]},
    "KOTAKBANK": {"company": "Kotak Mahindra Bank", "aliases": ["Kotak Bank", "Kotak Mahindra Bank Ltd"]},
    "LT": {"company": "Larsen & Toubro", "aliases": ["L&T", "Larsen and Toubro"]},
    "AXISBANK": {"company": "Axis Bank", "aliases": ["Axis Bank Ltd"]},
    "ITC": {"company": "ITC", "aliases": ["ITC Ltd"]},
    "BAJFINANCE": {"company": "Bajaj Finance", "aliases": ["Bajaj Finance Ltd"]},
    "ASIANPAINT": {"company": "Asian Paints", "aliases": ["Asian Paints Ltd"]},
    "MARUTI": {"company": "Maruti Suzuki", "aliases": ["Maruti Suzuki India", "Maruti Suzuki"]},
    "HCLTECH": {"company": "HCL Technologies", "aliases": ["HCL Tech", "HCL Technologies Ltd"]},
    "TITAN": {"company": "Titan Company", "aliases": ["Titan Company Ltd", "Titan"]},
    "SUNPHARMA": {"company": "Sun Pharmaceutical", "aliases": ["Sun Pharma", "Sun Pharmaceutical Industries"]},
    "WIPRO": {"company": "Wipro", "aliases": ["Wipro Ltd"]},
    "ULTRACEMCO": {"company": "UltraTech Cement", "aliases": ["UltraTech Cement Ltd", "Ultratech"]},
    "NESTLEIND": {"company": "Nestle India", "aliases": ["Nestle India Ltd"]},
    "TATAMOTORS": {"company": "Tata Motors", "aliases": ["Tata Motors Ltd"]},
    "POWERGRID": {"company": "Power Grid Corporation", "aliases": ["Power Grid", "PowerGrid"]},
    "NTPC": {"company": "NTPC", "aliases": ["NTPC Ltd"]},
    "ONGC": {"company": "Oil and Natural Gas Corporation", "aliases": ["ONGC Ltd", "Oil & Natural Gas Corporation"]},
    "JSWSTEEL": {"company": "JSW Steel", "aliases": ["JSW Steel Ltd"]},
    "TATASTEEL": {"company": "Tata Steel", "aliases": ["Tata Steel Ltd"]},
    "ADANIPORTS": {"company": "Adani Ports", "aliases": ["Adani Ports and SEZ", "Adani Ports & SEZ"]},
    "TECHM": {"company": "Tech Mahindra", "aliases": ["Tech Mahindra Ltd"]},
    "INDUSINDBK": {"company": "IndusInd Bank", "aliases": ["IndusInd Bank Ltd"]},
    "BAJAJFINSV": {"company": "Bajaj Finserv", "aliases": ["Bajaj Finserv Ltd"]},
    "GRASIM": {"company": "Grasim Industries", "aliases": ["Grasim Industries Ltd"]},
    "CIPLA": {"company": "Cipla", "aliases": ["Cipla Ltd"]},
    "HDFCLIFE": {"company": "HDFC Life", "aliases": ["HDFC Life Insurance", "HDFC Life Insurance Company"]},
    "DRREDDY": {"company": "Dr Reddys Laboratories", "aliases": ["Dr Reddy's", "Dr. Reddy's Laboratories"]},
    "COALINDIA": {"company": "Coal India", "aliases": ["Coal India Ltd"]},
    "DIVISLAB": {"company": "Divis Laboratories", "aliases": ["Divi's Laboratories", "Divis Labs"]},
    "BRITANNIA": {"company": "Britannia Industries", "aliases": ["Britannia Industries Ltd"]},
    "EICHERMOT": {"company": "Eicher Motors", "aliases": ["Eicher Motors Ltd"]},
    "APOLLOHOSP": {"company": "Apollo Hospitals", "aliases": ["Apollo Hospitals Enterprise"]},
    "SBILIFE": {"company": "SBI Life", "aliases": ["SBI Life Insurance", "SBI Life Insurance Company"]},
    "BPCL": {"company": "Bharat Petroleum", "aliases": ["BPCL", "Bharat Petroleum Corporation"]},
    "HEROMOTOCO": {"company": "Hero MotoCorp", "aliases": ["Hero MotoCorp Ltd", "Hero Motocorp"]},
    "TATACONSUM": {"company": "Tata Consumer Products", "aliases": ["Tata Consumer", "Tata Consumer Products Ltd"]},
    "UPL": {"company": "UPL", "aliases": ["UPL Ltd"]},
    "HINDALCO": {"company": "Hindalco Industries", "aliases": ["Hindalco", "Hindalco Industries Ltd"]},
    "BAJAJ_AUTO": {"company": "Bajaj Auto", "aliases": ["Bajaj Auto Ltd"]},
    "SHREECEM": {"company": "Shree Cement", "aliases": ["Shree Cement Ltd"]},
    "VEDL": {"company": "Vedanta", "aliases": ["Vedanta Ltd"]},
    "M_M": {"company": "Mahindra and Mahindra", "aliases": ["Mahindra & Mahindra", "M&M"]},
    "ADANIENT": {"company": "Adani Enterprises", "aliases": ["Adani Enterprises Ltd"]},
    "AMBUJACEM": {"company": "Ambuja Cements", "aliases": ["Ambuja Cement", "Ambuja Cements Ltd"]},
    "ASHOKLEY": {"company": "Ashok Leyland", "aliases": ["Ashok Leyland Ltd"]},
    "AUROPHARMA": {"company": "Aurobindo Pharma", "aliases": ["Aurobindo Pharma Ltd"]},
    "BANKBARODA": {"company": "Bank of Baroda", "aliases": ["Bank of Baroda Ltd"]},
    "BEL": {"company": "Bharat Electronics", "aliases": ["Bharat Electronics Ltd", "BEL"]},
    "CANBK": {"company": "Canara Bank", "aliases": ["Canara Bank Ltd"]},
    "CHOLAFIN": {"company": "Cholamandalam Investment", "aliases": ["Cholamandalam Investment and Finance", "Chola Finance"]},
    "DABUR": {"company": "Dabur India", "aliases": ["Dabur India Ltd"]},
    "DLF": {"company": "DLF", "aliases": ["DLF Ltd"]},
    "GAIL": {"company": "GAIL India", "aliases": ["GAIL", "GAIL (India)"]},
    "GODREJCP": {"company": "Godrej Consumer Products", "aliases": ["Godrej Consumer Products Ltd", "Godrej CP"]},
    "HAL": {"company": "Hindustan Aeronautics", "aliases": ["HAL", "Hindustan Aeronautics Ltd"]},
    "HAVELLS": {"company": "Havells India", "aliases": ["Havells India Ltd"]},
    "IOC": {"company": "Indian Oil", "aliases": ["Indian Oil Corporation", "IOC"]},
    "INDIGO": {"company": "InterGlobe Aviation", "aliases": ["IndiGo", "InterGlobe Aviation Ltd"]},
    "IRCTC": {"company": "IRCTC", "aliases": ["Indian Railway Catering and Tourism Corporation", "IRCTC Ltd"]},
    "JINDALSTEL": {"company": "Jindal Steel and Power", "aliases": ["Jindal Steel", "Jindal Steel & Power"]},
    "LUPIN": {"company": "Lupin", "aliases": ["Lupin Ltd"]},
    "PIDILITIND": {"company": "Pidilite Industries", "aliases": ["Pidilite Industries Ltd"]},
    "RECLTD": {"company": "REC", "aliases": ["REC Ltd", "Rural Electrification Corporation"]},
    "SIEMENS": {"company": "Siemens India", "aliases": ["Siemens Ltd", "Siemens India Ltd"]},
    "TATAPOWER": {"company": "Tata Power", "aliases": ["Tata Power Company", "Tata Power Co"]},
    "TVSMOTOR": {"company": "TVS Motor", "aliases": ["TVS Motor Company", "TVS Motor Company Ltd"]},
    "VARUNBEV": {"company": "Varun Beverages", "aliases": ["Varun Beverages Ltd"]},
}


def company_news_profile_for_ticker(ticker: str) -> dict[str, list[str] | str]:
    ticker = ticker.upper()
    if ticker in _COMPANY_PROFILES:
        return _COMPANY_PROFILES[ticker]
    fallback_name = ticker.replace("_", " ")
    return {"company": fallback_name, "aliases": [fallback_name]}


def company_news_query_for_ticker(ticker: str) -> str:
    profile = company_news_profile_for_ticker(ticker)
    aliases = [profile["company"], *profile.get("aliases", [])]
    unique_aliases = []
    for alias in aliases:
        alias = str(alias).strip()
        if alias and alias not in unique_aliases:
            unique_aliases.append(alias)
    alias_query = " OR ".join(f"\"{alias}\"" for alias in unique_aliases)
    return f"({alias_query}) AND (india OR nse OR bse OR stocks OR earnings OR results)"


def company_news_tickers(tickers: Iterable[str]) -> list[str]:
    return [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
