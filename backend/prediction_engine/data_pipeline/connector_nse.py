"""NSE direct data connector – STUB.

This module mirrors the interface of ``connector_yahoo.YahooConnector`` so
that a real NSE API integration can be swapped in later.

TODO
----
* Implement authentication against the NSE API.
* Handle rate limits and session rotation.
* Map instrument master list for ticker validation.
* Add intraday (1-min / 5-min) data support.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class NSEConnector:
    """Stub connector for direct NSE data access.

    All methods raise ``NotImplementedError`` until a real NSE data
    source is integrated.  The public API intentionally matches
    :class:`connector_yahoo.YahooConnector` so consumers can swap
    connectors via dependency injection.
    """

    REQUIRED_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]

    # TODO: add __init__ params for NSE API credentials / session config

    def fetch(
        self,
        ticker: str,
        start: str | datetime,
        end: str | datetime,
    ) -> pd.DataFrame:
        """Download OHLCV data for a single ticker.

        Parameters
        ----------
        ticker : str
            NSE symbol (e.g. ``RELIANCE``).
        start, end : str or datetime
            Date range.

        Returns
        -------
        pd.DataFrame

        Raises
        ------
        NotImplementedError
        """
        # TODO: implement real NSE API call
        raise NotImplementedError(
            "NSEConnector.fetch() is not yet implemented. "
            "Use YahooConnector as a fallback."
        )

    def fetch_to_csv(
        self,
        ticker: str,
        start: str | datetime,
        end: str | datetime,
        output_dir: str | Path,
    ) -> Path:
        """Fetch data and persist as CSV.

        Raises
        ------
        NotImplementedError
        """
        # TODO: implement once fetch() is ready
        raise NotImplementedError(
            "NSEConnector.fetch_to_csv() is not yet implemented."
        )
