#!/usr/bin/env python3
"""Market profile for the trader-* tools: US (the default) or NSE India.
Standard library only.

The same file sits in every skill folder that needs it, because a skill
folder is copied on its own and cannot import from its neighbours.
tests/test_market.py checks that the copies are identical: edit one, then
copy it over the others.

Which market, first match wins:
  1. TRADER_MARKET in the environment ("us" or "nse")
  2. "market" in trader/config.json (read from the folder you run in)
  3. "us"

"us" changes nothing: every tool keeps its own New York clock, NYSE
calendar and dollar text.

"nse" switches a tool to the NSE cash market:
  clock      India Standard Time, UTC+5:30, no daylight saving
  session    09:15 to 15:30, no early closes
  holidays   the NSE capital-market list for 2026 (circular NSE/CMTR/71775
             of 12 December 2025, plus 15 January 2026 from NSE/CMTR/72260).
             NSE publishes the next year's list each December: add it to
             NSE_HOLIDAYS and CALENDAR_YEARS below. The one-hour Muhurat
             session on Diwali is not a session here.
  symbols    plain NSE symbols (RELIANCE, M&M, BAJAJ-AUTO). Yahoo is asked
             for RELIANCE.NS; a symbol that already ends in .NS or .BO is
             sent as it is.
  money      "Rs " in place of "$" in everything a tool prints
  defaults   no entries before 09:30 or after 15:00, flat by 15:10 (ahead
             of the intraday square-off most Indian brokers run from about
             15:15). Limits when the config has none, in rupees: Rs 500 max
             loss per trade, Rs 1,500 a day, orders from Rs 100 to Rs 50,000.
             The config keys keep their _usd names.
  broker     "paper": a local paper ledger. No order leaves this computer.
"""

import contextlib
import datetime
import json
import os
import re
import sys
import urllib.parse

NSE_HOLIDAYS = {
    "2026-01-15": "Municipal Corporation Election, Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}

PROFILES = {
    "us": {
        "name": "us", "exchange": "NYSE", "tz": "ET", "place": "New York", "currency": "$",
        "calendar_site": "nyse.com",
    },
    "nse": {
        "name": "nse", "exchange": "NSE", "tz": "IST", "place": "India", "currency": "Rs ",
        "calendar_site": "nseindia.com",
        "utc_offset_hours": 5.5,
        "open": datetime.time(9, 15),
        "close": datetime.time(15, 30),
        "holidays": NSE_HOLIDAYS,
        "early_close": {},
        "calendar_years": (2026,),
        "yahoo_suffix": ".NS",
        "no_entries_before": "09:30",
        "no_entries_after": "15:00",
        "flat_by": "15:10",
        "min_price": 50.0,
        "min_volume": 500000,
        # the config keys keep their _usd names; on the NSE the amounts are rupees
        "limits": {"max_order_usd": 50000, "min_order_usd": 100, "max_loss_per_trade_usd": 500,
                   "max_daily_loss_usd": 1500, "broker": "paper"},
    },
}

# An NSE symbol: letters, digits, & and -, up to 10 characters (M&M, BAJAJ-AUTO,
# 3MINDIA), with an optional Yahoo suffix the user typed themselves.
NSE_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,14}(\.(NS|BO))?$")


def detect(config="trader/config.json", environ=None):
    """The market's name: TRADER_MARKET, then the config's "market", then "us"."""
    env = os.environ if environ is None else environ
    raw = env.get("TRADER_MARKET")
    if not raw and config and os.path.exists(config):
        try:
            with open(config, encoding="utf-8") as fh:
                doc = json.load(fh)
            raw = doc.get("market") if isinstance(doc, dict) else None
        except (ValueError, OSError):
            raw = None
    name = str(raw or "us").strip().lower()
    if name in ("india", "nse-india", "in"):
        name = "nse"
    if name not in PROFILES:
        raise ValueError("market must be one of %s, got %r" % (", ".join(sorted(PROFILES)), raw))
    return name


def profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError("market must be one of %s, got %r" % (", ".join(sorted(PROFILES)), name))


def yahoo_symbol(name, sym):
    """Our symbol -> the one Yahoo knows. US: BRK.B -> BRK-B. NSE: RELIANCE -> RELIANCE.NS."""
    s = str(sym).strip().upper()
    if name == "us":
        return s.replace(".", "-")
    if s.endswith((".NS", ".BO")) or s.startswith("^"):
        return s
    return s + PROFILES[name]["yahoo_suffix"]


def yahoo_quoted(name, sym):
    """yahoo_symbol, safe to put in a URL (M&M.NS -> M%26M.NS). US tickers come out unchanged."""
    return urllib.parse.quote(yahoo_symbol(name, sym), safe="-.^")


def from_yahoo(name, ysym):
    """Yahoo's symbol -> ours. US: BRK-B -> BRK.B. NSE: RELIANCE.NS -> RELIANCE."""
    s = str(ysym).strip().upper()
    if name == "us":
        return s.replace("-", ".")
    suffix = PROFILES[name]["yahoo_suffix"]
    return s[:-len(suffix)] if s.endswith(suffix) else s


def same_symbol(name, ysym, sym):
    """Is Yahoo's symbol the one we asked for?"""
    return str(ysym).strip().upper() == yahoo_symbol(name, sym)


def ticker_ok(name, sym):
    """NSE only: does this look like an NSE symbol? (US tools keep their own rule.)"""
    return bool(NSE_TICKER.match(str(sym).strip().upper()))


_NSE_WORDS = [
    (re.compile(r"New York time"), "India time"),
    (re.compile(r"New York \(ET\)"), "India (IST)"),
    (re.compile(r"New York"), "India"),
    (re.compile(r"nyse\.com"), "nseindia.com"),
    (re.compile(r"\bNYSE\b"), "NSE"),
    (re.compile(r"\bET\b"), "IST"),
    (re.compile(r"\$"), "Rs "),
]


def relabel(name, text):
    """Text a US tool printed -> the same text for this market (clock name, exchange, money)."""
    if name == "us" or not isinstance(text, str):
        return text
    for rx, word in _NSE_WORDS:
        text = rx.sub(word, text)
    return text


class _Relabel(object):
    """A stream that relabels what is written to it."""

    def __init__(self, stream, name):
        self._stream = stream
        self._name = name

    def write(self, text):
        return self._stream.write(relabel(self._name, text))

    def __getattr__(self, attr):
        return getattr(self._stream, attr)


@contextlib.contextmanager
def output(name):
    """Inside this block, everything printed is relabelled for the market. "us": no change."""
    if name == "us":
        yield
        return
    out, err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Relabel(out, name), _Relabel(err, name)
    try:
        yield
    finally:
        sys.stdout, sys.stderr = out, err
