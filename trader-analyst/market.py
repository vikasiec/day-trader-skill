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


# ---------------------------------------------------------------- NSE tick size

# NSE price-banded tick sizes for the cash (CM) segment, effective
# April 15, 2025 (as summarized by zerodha.com/marketintel bulletin
# 408151 and marketcalls.in, both citing NSE circular NSE/CMTR/67133
# which partially modifies the May 2024 revision NSE/CMTR/62174;
# read 2026-11-14). The tick for a stock is set monthly from its
# previous-month close; ETFs are excluded. Near a band boundary,
# the broker's tick may differ from the one this code picks from
# the current price.
_US_TICK = 0.01


def tick_size(name, price):
    """The tick size for this price. US: always 0.01. NSE: price-banded."""
    if name == "us":
        return _US_TICK
    p = abs(float(price))
    if p < 250:
        return 0.01
    if p <= 1000:
        return 0.05
    if p <= 5000:
        return 0.10
    if p <= 10000:
        return 0.50
    if p <= 20000:
        return 1.00
    return 5.00


def round_to_tick(name, price, direction="nearest"):
    """Round a price to the market's tick size.

    direction:
      "nearest"  normal rounding (half away from zero)
      "down"     toward zero (for a long's stop, away from entry)
      "up"       away from zero (for a long's target)

    US: rounds to the cent. NSE: price-banded ticks."""
    tick = tick_size(name, price)
    p = round(float(price) * 100)
    t = round(tick * 100)
    if direction == "down":
        return (p // t * t) / 100.0
    elif direction == "up":
        return (-(-p // t) * t) / 100.0
    else:
        return (((p + t // 2) // t) * t) / 100.0


# ---------------------------------------------------------------- NSE intraday transaction costs

# Default charges for NSE cash equity intraday (MIS/CO) trades. Statutory
# rates (STT, exchange, SEBI, stamp duty, GST) are from SEBI and NSE fee
# schedules; brokerage is the typical discount-broker tariff. Verify
# against your own broker's schedule before relying on these defaults.
_NSE_BROKERAGE_FLAT = 20.0          # Rs per executed order (discount broker cap)
_NSE_BROKERAGE_PCT = 0.0003         # 0.03% - the lesser of flat and pct applies
_NSE_STT_PCT = 0.00025              # 0.025% on sell side only (intraday equity)
_NSE_EXCHANGE_TURNOVER_PCT = 0.0000297   # NSE transaction charge
_NSE_SEBI_FEE_PCT = 0.000001        # SEBI turnover fee
_NSE_STAMP_DUTY_PCT = 0.00003       # 0.003% on buy side (state-level, capped)
_NSE_GST_PCT = 0.18                 # 18% GST on brokerage + exchange + SEBI

# Slippage is an estimate, not a statutory charge. Config key overrides it.
_NSE_SLIPPAGE_PER_LEG_PCT = 0.0003  # 0.03% per leg, conservative for liquid stocks


def nse_charges(buy_value, sell_value, slippage_per_leg_pct=None):
    """Round-trip transaction costs for an NSE intraday equity trade.

    Returns a dict with each component and the total, all in rupees."""
    if slippage_per_leg_pct is None:
        slippage_per_leg_pct = _NSE_SLIPPAGE_PER_LEG_PCT
    buy_brokerage = min(_NSE_BROKERAGE_FLAT, buy_value * _NSE_BROKERAGE_PCT)
    sell_brokerage = min(_NSE_BROKERAGE_FLAT, sell_value * _NSE_BROKERAGE_PCT)
    brokerage = buy_brokerage + sell_brokerage
    stt = sell_value * _NSE_STT_PCT
    turnover = buy_value + sell_value
    exchange_turnover = turnover * _NSE_EXCHANGE_TURNOVER_PCT
    sebi_fee = turnover * _NSE_SEBI_FEE_PCT
    stamp_duty = buy_value * _NSE_STAMP_DUTY_PCT
    gst = (brokerage + exchange_turnover + sebi_fee) * _NSE_GST_PCT
    slippage = (buy_value + sell_value) * slippage_per_leg_pct
    statutory = brokerage + stt + exchange_turnover + sebi_fee + stamp_duty + gst
    total = statutory + slippage
    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_turnover": round(exchange_turnover, 2),
        "sebi_fee": round(sebi_fee, 2),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "slippage": round(slippage, 2),
        "slippage_pct": slippage_per_leg_pct,
        "statutory": round(statutory, 2),
        "total": round(total, 2),
    }


def trade_charges(name, qty, entry, stop, cfg=None):
    """Estimated round-trip charges for a trade of qty shares at entry, exiting at stop.

    Returns {"charges": total, "breakdown": {...}} or {"charges": 0, "breakdown": None}
    for the US market. The config key "slippage_pct" overrides the default estimate."""
    if name == "us":
        return {"charges": 0.0, "breakdown": None}
    slip = None
    if isinstance(cfg, dict):
        v = cfg.get("slippage_pct")
        if v is not None:
            try:
                slip = float(v)
            except (TypeError, ValueError):
                pass
    buy_value = qty * float(entry)
    sell_value = qty * float(stop)
    bd = nse_charges(buy_value, sell_value, slip)
    return {"charges": bd["total"], "breakdown": bd}
