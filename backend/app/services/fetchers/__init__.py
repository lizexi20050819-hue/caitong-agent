"""10-dimension A-share data fetchers (akshare + baostock)."""

from backend.app.services.fetchers.fetch_financials import fetch_financials
from backend.app.services.fetchers.fetch_industry import fetch_industry
from backend.app.services.fetchers.fetch_capital_flow import fetch_capital_flow
from backend.app.services.fetchers.fetch_lhb import fetch_lhb
from backend.app.services.fetchers.fetch_sentiment import fetch_sentiment
from backend.app.services.fetchers.fetch_peers import fetch_peers
from backend.app.services.fetchers.fetch_valuation import fetch_valuation
from backend.app.services.fetchers.fetch_events import fetch_events
from backend.app.services.fetchers.fetch_fund_holders import fetch_fund_holders
from backend.app.services.fetchers.fetch_research import fetch_research

__all__ = [
    "fetch_financials", "fetch_industry", "fetch_capital_flow",
    "fetch_lhb", "fetch_sentiment", "fetch_peers", "fetch_valuation",
    "fetch_events", "fetch_fund_holders", "fetch_research",
]
