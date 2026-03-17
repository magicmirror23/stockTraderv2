from backend.prediction_engine.data_pipeline.connector_news import NewsConnector
from backend.prediction_engine.data_pipeline.connector_yahoo import YahooConnector


def test_yahoo_connector_uses_aliases_for_problem_tickers():
    connector = YahooConnector()

    assert connector._yahoo_tickers("VARUNBEV") == ["VBL.NS", "VARUNBEV.NS"]
    assert connector._yahoo_tickers("TATAMOTORS") == ["TATAMOTORS.NS", "500570.BO"]


def test_news_connector_parses_sanitized_rss_payload():
    xml = """
    <rss><channel>
      <item>
        <title>Reliance & Jio sign investment deal</title>
        <source>ExampleWire</source>
        <pubDate>Tue, 17 Mar 2026 12:30:00 GMT</pubDate>
      </item>
    </channel></rss>
    """

    records = NewsConnector()._parse_rss("RELIANCE", xml)

    assert len(records) == 1
    assert records[0].topic == "RELIANCE"
    assert records[0].source == "ExampleWire"
    assert "Reliance" in records[0].headline
