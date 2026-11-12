"""A synthetic NSE chart for the tests: Yahoo v8 chart JSON, 5-minute bars, 09:15 to 15:30 IST.

Invented prices, real calendar: weekends and the NSE holidays in market.py have no
bars. The last day is a planted opening-range breakout:
  09:15 to 09:30  the range, high 1410.00, low 1400.00
  09:30 to 09:45  three quiet bars under the high
  09:45 to 09:50  closes at 1412.50, the first close above the range
  09:50 to 10:00  two more bars, then the data stops
"""

import datetime
import json

EPOCH = datetime.datetime(1970, 1, 1)
IST = datetime.timedelta(hours=5, minutes=30)
BARS = 75  # 09:15 to 15:30 in 5-minute bars


def _ts(day, minutes_after_open):
    local = datetime.datetime.combine(day, datetime.time(9, 15)) + datetime.timedelta(minutes=minutes_after_open)
    return int((local - IST - EPOCH).total_seconds())


def trading_days(last, n, holidays):
    """The n trading days that end on `last`, oldest first."""
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in holidays:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out[::-1]


def chart(holidays, symbol="RELIANCE.NS", last=datetime.date(2026, 11, 12), full_sessions=30):
    """-> (json text, the last day). `full_sessions` whole days, then the breakout day."""
    days = trading_days(last, full_sessions + 1, holidays)
    t, o, h, l, c, v = [], [], [], [], [], []
    seed = 20261112
    price = 1380.0
    for d in days[:-1]:
        for i in range(BARS):
            seed = (seed * 1103515245 + 12345) % (1 << 31)
            step = ((seed >> 8) % 801 - 400) / 100.0            # -4.00 to +4.00 rupees a bar
            seed = (seed * 1103515245 + 12345) % (1 << 31)
            wick = ((seed >> 8) % 300) / 100.0                    # 0.00 to 2.99
            op = price
            cl = round(max(900.0, price + step), 2)
            t.append(_ts(d, 5 * i))
            o.append(op)
            h.append(round(max(op, cl) + wick, 2))
            l.append(round(min(op, cl) - wick, 2))
            c.append(cl)
            v.append(40000 + (seed >> 5) % 60000)
            price = cl
    plant = [  # (open, high, low, close) on the breakout day
        (1402.0, 1408.0, 1400.0, 1406.0), (1406.0, 1410.0, 1403.0, 1404.0), (1404.0, 1409.0, 1402.0, 1407.0),
        (1407.0, 1409.5, 1405.0, 1408.0), (1408.0, 1409.8, 1406.0, 1409.0), (1409.0, 1409.9, 1407.0, 1409.5),
        (1409.5, 1413.0, 1409.0, 1412.5), (1412.5, 1415.0, 1411.0, 1414.0), (1414.0, 1416.0, 1412.0, 1415.0),
    ]
    for i, (op, hi, lo, cl) in enumerate(plant):
        t.append(_ts(days[-1], 5 * i))
        o.append(op)
        h.append(hi)
        l.append(lo)
        c.append(cl)
        v.append(90000 if i == 6 else 50000)
    meta = {"symbol": symbol, "currency": "INR", "exchangeName": "NSI", "exchangeTimezoneName": "Asia/Kolkata",
            "gmtoffset": 19800, "dataGranularity": "5m", "regularMarketPrice": c[-1],
            "regularMarketTime": t[-1] + 300, "chartPreviousClose": c[-len(plant) - 1], "previousClose": c[-len(plant) - 1]}
    doc = {"chart": {"result": [{"meta": meta, "timestamp": t,
                                 "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}],
                     "error": None}}
    return json.dumps(doc), days[-1]
