"""NSE India mode: the market profile and one trade through the whole chain, offline.

The chart is synthetic (tests/_nse.py); the calendar is the real NSE list for 2026.
"""

import contextlib
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest

import _nse
from _load import ROOT, load

FOLDERS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
           "trader-budget", "trader-risk", "trader-broker", "trader-alerts"]
TOOLS = {"trader-scanner": "scan", "trader-news": "news", "trader-entry": "entry", "trader-exit": "exit",
         "trader-timemachine": "timemachine", "trader-budget": "size", "trader-risk": "check",
         "trader-broker": "ticket", "trader-alerts": "alerts"}

market = load("trader-scanner", "market")
NOW = "2026-11-12 10:02"


def run(mod, argv):
    """mod.main(argv) -> (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Profile(unittest.TestCase):
    def test_every_folder_has_the_same_market_file(self):
        with open(os.path.join(ROOT, FOLDERS[0], "market.py"), encoding="utf-8") as fh:
            first = fh.read()
        for f in FOLDERS[1:]:
            with open(os.path.join(ROOT, f, "market.py"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), first, f)

    def test_detect_env_then_config_then_us(self):
        tmp = tempfile.mkdtemp()
        try:
            cfg = os.path.join(tmp, "config.json")
            self.assertEqual(market.detect(cfg, {}), "us")
            with open(cfg, "w") as fh:
                json.dump({"market": "NSE"}, fh)
            self.assertEqual(market.detect(cfg, {}), "nse")
            self.assertEqual(market.detect(cfg, {"TRADER_MARKET": "us"}), "us")
            self.assertEqual(market.detect(cfg, {"TRADER_MARKET": "india"}), "nse")
            with self.assertRaises(ValueError):
                market.detect(cfg, {"TRADER_MARKET": "lse"})
        finally:
            shutil.rmtree(tmp)

    def test_symbols_to_yahoo_and_back(self):
        self.assertEqual(market.yahoo_symbol("us", "brk.b"), "BRK-B")
        self.assertEqual(market.from_yahoo("us", "BRK-B"), "BRK.B")
        self.assertEqual(market.yahoo_symbol("nse", "reliance"), "RELIANCE.NS")
        self.assertEqual(market.yahoo_symbol("nse", "RELIANCE.NS"), "RELIANCE.NS")
        self.assertEqual(market.yahoo_symbol("nse", "500325.BO"), "500325.BO")
        self.assertEqual(market.yahoo_symbol("nse", "BAJAJ-AUTO"), "BAJAJ-AUTO.NS")
        self.assertEqual(market.yahoo_quoted("nse", "M&M"), "M%26M.NS")
        self.assertEqual(market.yahoo_quoted("us", "BRK.B"), "BRK-B")
        self.assertEqual(market.from_yahoo("nse", "BAJAJ-AUTO.NS"), "BAJAJ-AUTO")
        self.assertTrue(market.same_symbol("nse", "M&M.NS", "m&m"))
        for good in ("RELIANCE", "M&M", "BAJAJ-AUTO", "3MINDIA", "TCS.NS"):
            self.assertTrue(market.ticker_ok("nse", good), good)
        for bad in ("", "REL IANCE", "BTC/USD", "TSLA261218C00400000X", "-ABC"):
            self.assertFalse(market.ticker_ok("nse", bad), bad)

    def test_relabel_changes_clock_exchange_and_money_only_on_the_nse(self):
        text = "It is 10:15 AM ET: the NYSE is open (New York time). Stop $358.32, an ETF, TARGET."
        self.assertEqual(market.relabel("us", text), text)
        self.assertEqual(market.relabel("nse", text),
                         "It is 10:15 AM IST: the NSE is open (India time). Stop Rs 358.32, an ETF, TARGET.")

    def test_the_nse_calendar(self):
        p = market.profile("nse")
        self.assertEqual((p["open"], p["close"]), (datetime.time(9, 15), datetime.time(15, 30)))
        self.assertEqual(len(p["holidays"]), 16)
        for iso in p["holidays"]:
            d = datetime.date.fromisoformat(iso)
            self.assertLess(d.weekday(), 5, "%s is a weekend: weekends are closed anyway" % iso)
            self.assertIn(d.year, p["calendar_years"])


class EveryTool(unittest.TestCase):
    def test_use_market_switches_and_switches_back(self):
        for folder in FOLDERS:
            mod = load(folder, TOOLS[folder])
            us = mod.eastern_offset(datetime.datetime(2026, 11, 12, 4, 30))
            self.assertEqual(us, -5, folder)
            before = {k: (dict(v) if isinstance(v, dict) else v) for k, v in vars(mod).items()
                      if k in mod._MARKET_GLOBALS}
            mod.use_market("nse")
            try:
                self.assertEqual(mod.MARKET, "nse", folder)
                self.assertEqual(mod.eastern_offset(datetime.datetime(2026, 11, 12, 4, 30)), 5.5, folder)
                self.assertEqual(mod.to_eastern(datetime.datetime(2026, 11, 12, 4, 30)),
                                 datetime.datetime(2026, 11, 12, 10, 0), folder)
                if hasattr(mod, "eastern_to_utc"):
                    self.assertEqual(mod.eastern_to_utc(datetime.datetime(2026, 11, 12, 10, 0)),
                                     datetime.datetime(2026, 11, 12, 4, 30), folder)
                if "OPEN" in before:
                    self.assertEqual((mod.OPEN, mod.CLOSE, mod.EARLY),
                                     (datetime.time(9, 15), datetime.time(15, 30), datetime.time(15, 30)), folder)
                if "NYSE_HOLIDAYS" in before:
                    self.assertIn("2026-11-10", mod.NYSE_HOLIDAYS, folder)
                    self.assertNotIn("2026-11-26", mod.NYSE_HOLIDAYS, folder)   # Thanksgiving is a session in Mumbai
                if "SESSION_BARS" in before:
                    self.assertEqual((mod.SESSION_BARS, mod.OPEN_MIN, mod.CLOSE_MIN), (75, 555, 930), folder)
                if "DEFAULTS" in before and "flat_by" in before["DEFAULTS"]:
                    self.assertEqual(mod.DEFAULTS["flat_by"], "15:10", folder)
            finally:
                mod.use_market("us")
            after = {k: (dict(v) if isinstance(v, dict) else v) for k, v in vars(mod).items()
                     if k in mod._MARKET_GLOBALS}
            self.assertEqual(after, before, folder)

    def test_a_bad_market_name_stops_the_tool_with_a_plain_message(self):
        mod = load("trader-alerts", "alerts")
        os.environ["TRADER_MARKET"] = "lse"
        try:
            code, out, err = run(mod, ["clock"])
        finally:
            del os.environ["TRADER_MARKET"]
        self.assertEqual(code, 1)
        self.assertIn("market must be one of nse, us", err)


class OneTradeOnTheNSE(unittest.TestCase):
    """scanner -> entry -> exit -> timemachine -> budget -> risk -> broker -> alerts, RELIANCE, offline."""

    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)
        os.makedirs("trader")
        with open("trader/config.json", "w") as fh:
            json.dump({"market": "nse", "budget": 100000}, fh)      # the config alone picks the market
        text, self.day = _nse.chart(market.NSE_HOLIDAYS)
        os.makedirs("charts")
        with open("charts/RELIANCE.json", "w") as fh:
            fh.write(text)
        with open("charts/RELIANCE-60d5m.json", "w") as fh:
            fh.write(text)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.tmp)

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_chain(self):
        # scanner: the planted breakout, on the IST clock
        scan = load("trader-scanner", "scan")
        code, out, err = run(scan, ["orb", "--offline", "charts/RELIANCE.json", "--now", NOW, "--at", "10:00"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("IST", out)
        self.assertIn("15-minute range (9:15 to 9:30 AM)", out)
        self.assertNotIn("$", out)
        hit = self.read("trader/watchlist.json")["hits"][0]
        self.assertEqual((hit["symbol"], hit["at"], hit["price"], hit["or_high"], hit["or_low"]),
                         ("RELIANCE", "9:50 AM", 1412.5, 1410.0, 1400.0))

        # entry: triggered at the 09:45 bar's close
        entry = load("trader-entry", "entry")
        code, out, err = run(entry, ["check", "RELIANCE", "--offline", "charts", "--now", NOW, "--write"])
        self.assertEqual(code, 0, out + err)
        e = self.read("trader/entry.json")
        self.assertEqual((e["symbol"], e["status"], e["price"]), ("RELIANCE", "triggered", 1412.5))
        self.assertEqual(e["opening_range"]["high"], 1410.0)
        self.assertIn("Rs 1412.50", out)

        # exit: stop at the range's midpoint, the default 2R target, flat by 15:10
        exit_ = load("trader-exit", "exit")
        code, out, err = run(exit_, ["plan", "--now", NOW, "--write"])
        self.assertEqual(code, 0, out + err)
        plan = self.read("trader/plan.json")
        self.assertEqual((plan["symbol"], plan["entry"], plan["stop"], plan["target"], plan["flat_by"]),
                         ("RELIANCE", 1412.5, 1405.0, 1427.5, "15:10"))   # the default target is 2R
        self.assertIn("IST", out)

        # time machine: 75-bar sessions, replays run to the 15:30 close
        tm = load("trader-timemachine", "timemachine")
        code, out, err = run(tm, ["run", "--offline", "charts", "--now", NOW, "--replays", "400", "--write"])
        self.assertEqual(code, 0, out + err)
        doc = self.read("trader/timemachine.json")
        self.assertEqual(doc["mc"]["pool_sessions"], 30)
        self.assertEqual(doc["mc"]["until"], "15:30")
        self.assertEqual(doc["plan"]["entry_bar"], 6)
        self.assertEqual(doc["mc"]["bars_left"], 75 - 1 - 6)
        self.assertEqual(doc["data"]["symbol"], "RELIANCE")
        self.assertTrue(doc["data"]["last_bar"].endswith("IST"))
        self.assertAlmostEqual(doc["mc"]["p_target"] + doc["mc"]["p_stop"] + doc["mc"]["p_neither"], 1.0, places=3)
        self.assertEqual(doc["history"]["sessions"], 30)

        # budget: Rs 500 max loss (with charges) < 66 shares, but Rs 50,000 max order / 1412.50 = 35
        size = load("trader-budget", "size")
        code, out, err = run(size, ["--now", NOW, "--write"])
        self.assertEqual(code, 0, out + err)
        order = self.read("trader/orders.json")["orders"][0]
        self.assertEqual((order["symbol"], order["side"], order["qty"]), ("RELIANCE", "buy", "35"))
        self.assertIn("Rs ", out)
        self.assertNotIn("$", out)

        # risk: inside every limit, inside the 09:30 to 15:00 entry window
        check = load("trader-risk", "check")
        code, out, err = run(check, ["--now", NOW])
        self.assertEqual(code, 0, out + err)
        self.assertIn("PASS", out)

        # broker: a local paper ledger, never a connector
        ticket = load("trader-broker", "ticket")
        code, out, err = run(ticket, ["show", "--now", NOW])
        self.assertEqual(code, 0, out + err)
        self.assertIn("local paper ledger", out)
        self.assertIn("goes to no", out)
        self.assertNotIn("place_stock_order", out)
        self.assertNotIn("Alpaca", out)
        code, out, err = run(ticket, ["approve", "--index", "1", "--reply", "yes", "--now", NOW])
        self.assertEqual(code, 0, out + err)
        self.assertIn("no order is sent anywhere", out)
        code, out, err = run(ticket, ["result", "--index", "1", "--status", "placed", "--filled-qty", "35",
                                     "--filled-price", "1412.5", "--now", NOW])
        self.assertEqual(code, 0, out + err)
        rec = self.read("trader/state/broker.json")["orders"][0]
        self.assertEqual((rec["broker"], rec["paper"]), ("paper", True))
        self.assertTrue(rec["at"].endswith("+05:30"), rec["at"])
        pos = self.read("trader/portfolio.json")["positions"][0]
        self.assertEqual(float(pos.get("shares", pos.get("qty"))), 35.0)

        # alerts: the plan's stop, target and the 15:10 flat-by
        alerts = load("trader-alerts", "alerts")
        code, out, err = run(alerts, ["add", "--from-plan"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("15:10", out)

        # flatten: a sell ticket for the paper ledger
        code, out, err = run(ticket, ["flatten", "--symbol", "RELIANCE", "--now", "2026-11-12 15:05"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("flat by 15:10 India", out)
        self.assertNotIn("Alpaca", out)

    def test_the_clock_knows_the_nse_session_and_holidays(self):
        alerts = load("trader-alerts", "alerts")
        code, out, err = run(alerts, ["clock", "--now", "2026-11-12 10:00"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("NSE OPEN", out)
        self.assertIn("09:15 to 15:30", out)
        code, out, err = run(alerts, ["clock", "--now", "2026-11-10 11:00"])
        self.assertEqual(code, 1)
        self.assertIn("NSE closed", out)
        self.assertIn("Diwali Balipratipada", out)
        self.assertIn("Next open: 2026-11-11 09:15 India", out)
        code, out, err = run(alerts, ["clock", "--now", "2026-11-26 11:00"])    # Thanksgiving: open in Mumbai
        self.assertEqual(code, 0, out + err)
        code, out, err = run(alerts, ["clock", "--now", "2027-01-04 11:00"])    # no 2027 list yet: say so
        self.assertIn("Holiday list covers 2026 only: check nseindia.com", out)

    def test_entry_waits_before_the_range_is_set_and_says_closed_on_a_holiday(self):
        entry = load("trader-entry", "entry")
        code, out, err = run(entry, ["check", "RELIANCE", "--offline", "charts", "--now", "2026-11-12 09:20"])
        self.assertEqual(code, 1, out + err)
        self.assertNotIn("TRIGGERED", out)
        code, out, err = run(entry, ["check", "RELIANCE", "--offline", "charts", "--now", "2026-11-10 10:00"])
        self.assertIn("NSE is closed today", out + err)

    def test_universe_from_the_nifty_500_file(self):
        scan = load("trader-scanner", "scan")
        os.makedirs("nse")
        with open("nse/ind_nifty500list.csv", "w") as fh:
            fh.write("Company Name,Industry,Symbol,Series,ISIN Code\n"
                     "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\n"
                     "Mahindra & Mahindra Ltd.,Automobile and Auto Components,M&M,EQ,INE101A01026\n"
                     "Bajaj Auto Ltd.,Automobile and Auto Components,BAJAJ-AUTO,EQ,INE917I01010\n"
                     "Some Trust,Realty,SOMEREIT,RR,INE000000000\n")
        code, out, err = run(scan, ["universe", "--offline", "nse"])
        self.assertEqual(code, 0, out + err)
        with open("trader/universe.txt") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines, ["BAJAJ-AUTO|Bajaj Auto Ltd.", "M&M|Mahindra & Mahindra Ltd.",
                                 "RELIANCE|Reliance Industries Ltd."])
        code, out, err = run(scan, ["universe", "--offline", "charts"])     # no list there: a plain error
        self.assertEqual(code, 1)
        self.assertIn("no ind_nifty500list.csv", err)

    def test_universe_falls_back_to_the_built_in_list_when_nse_does_not_answer(self):
        scan = load("trader-scanner", "scan")

        def down(url, timeout=20):
            raise OSError("no network in tests")
        scan.http_get = down
        code, out, err = run(scan, ["universe"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("did not download", out)
        with open("trader/universe.txt") as fh:
            syms = [ln.split("|")[0] for ln in fh.read().splitlines()]
        self.assertEqual(syms, sorted(scan.NSE_FALLBACK))
        self.assertIn("M&M", syms)

    def test_yahoo_urls_carry_the_ns_suffix(self):
        scan = load("trader-scanner", "scan")
        news = load("trader-news", "news")
        alerts = load("trader-alerts", "alerts")
        tm = load("trader-timemachine", "timemachine")
        for mod in (scan, news, alerts, tm):
            mod.use_market("nse")
        self.assertEqual(scan.spark_path(["RELIANCE", "M&M"], "1d", "5m"),
                         "/v7/finance/spark?symbols=RELIANCE.NS,M%26M.NS&range=1d&interval=5m")
        self.assertIn("s=M%26M.NS&region=IN&lang=en-IN", news.headlines_url("M&M"))
        self.assertIn("/v8/finance/chart/RELIANCE.NS?", alerts.yahoo_url("reliance"))
        self.assertIn("/v8/finance/chart/BAJAJ-AUTO.NS?", tm.chart_url("BAJAJ-AUTO"))
        with self.assertRaises(alerts.AlertError):
            alerts.stooq_url("RELIANCE")

    def test_news_skips_sec_filings_on_the_nse(self):
        news = load("trader-news", "news")
        os.makedirs("feeds")
        code, out, err = run(news, ["--tickers", "RELIANCE", "--offline", "feeds", "--no-moves", "--dry-run"])
        self.assertIn("SEC filings are US only", out + err)
        self.assertNotIn("sec_user_agent", out + err)


class TickRounding(unittest.TestCase):
    """round_to_tick integer-paise arithmetic and tick_size band boundaries."""

    def test_on_tick_prices_are_unchanged(self):
        cases = [
            (100.0, 0.01), (249.99, 0.01),
            (250.0, 0.05), (500.0, 0.05), (1000.0, 0.05),
            (1000.10, 0.10), (2500.0, 0.10), (5000.0, 0.10),
            (5000.50, 0.50), (7500.0, 0.50), (10000.0, 0.50),
            (10001.0, 1.0), (15000.0, 1.0), (20000.0, 1.0),
            (20005.0, 5.0), (50000.0, 5.0),
        ]
        for price, expected_tick in cases:
            self.assertEqual(market.tick_size("nse", price), expected_tick,
                             "tick_size(%s) should be %s" % (price, expected_tick))
            for d in ("nearest", "down", "up"):
                self.assertEqual(market.round_to_tick("nse", price, d), price,
                                 "round_to_tick(%s, %s) should stay %s" % (price, d, price))

    def test_band_boundaries(self):
        self.assertEqual(market.tick_size("nse", 249.99), 0.01)
        self.assertEqual(market.tick_size("nse", 250.0), 0.05)
        self.assertEqual(market.tick_size("nse", 1000.0), 0.05)
        self.assertEqual(market.tick_size("nse", 1000.01), 0.10)
        self.assertEqual(market.tick_size("nse", 5000.0), 0.10)
        self.assertEqual(market.tick_size("nse", 5000.01), 0.50)
        self.assertEqual(market.tick_size("nse", 10000.0), 0.50)
        self.assertEqual(market.tick_size("nse", 10000.01), 1.00)
        self.assertEqual(market.tick_size("nse", 20000.0), 1.00)
        self.assertEqual(market.tick_size("nse", 20000.01), 5.00)

    def test_float_precision_regression(self):
        self.assertEqual(market.round_to_tick("nse", 1000.30, "down"), 1000.30)
        self.assertEqual(market.round_to_tick("nse", 1000.30, "up"), 1000.30)
        self.assertEqual(market.round_to_tick("nse", 1000.30, "nearest"), 1000.30)

    def test_off_tick_rounding(self):
        self.assertEqual(market.round_to_tick("nse", 1405.03, "down"), 1405.0)
        self.assertEqual(market.round_to_tick("nse", 1405.03, "up"), 1405.1)
        self.assertEqual(market.round_to_tick("nse", 249.97, "down"), 249.97)
        self.assertEqual(market.round_to_tick("nse", 249.97, "up"), 249.97)
        self.assertEqual(market.round_to_tick("nse", 500.03, "down"), 500.0)
        self.assertEqual(market.round_to_tick("nse", 500.03, "up"), 500.05)

    def test_us_tick_is_always_one_cent(self):
        self.assertEqual(market.tick_size("us", 1.0), 0.01)
        self.assertEqual(market.tick_size("us", 50000.0), 0.01)


class NSEChargesAndTickRounding(unittest.TestCase):
    """Budget and risk agree on NSE when max-loss binds, the stop is off-tick,
    and charges are counted."""

    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)
        os.makedirs("trader")
        with open("trader/config.json", "w") as fh:
            json.dump({"market": "nse", "budget": 500000,
                       "max_loss_per_trade_usd": 500,
                       "max_order_usd": 500000,
                       "max_position_pct": 100,
                       "max_daily_loss_usd": 5000}, fh)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.tmp)

    def test_budget_and_risk_agree_on_nse_with_off_tick_stop(self):
        size = load("trader-budget", "size")
        check = load("trader-risk", "check")
        size.use_market("nse")
        check.use_market("nse")
        try:
            plan = {"symbol": "RELIANCE", "side": "buy", "entry": 1412.50,
                    "stop": 1405.03, "target": 1427.50, "setup": "orb",
                    "date": "2026-11-12", "entry_time": "10:00 AM", "flat_by": "15:10"}
            cfg = {"budget": 500000, "max_loss_per_trade_usd": 500,
                   "max_order_usd": 500000, "max_position_pct": 100,
                   "max_daily_loss_usd": 5000, "max_trades_per_day": 3,
                   "max_orders_per_day": 10, "min_reward_risk": 1.0,
                   "require_stop": True, "paper": True,
                   "no_entries_before": "09:30", "no_entries_after": "15:00",
                   "cash_buffer_pct": 10, "min_order_usd": 100,
                   "blocked": [], "allow_options": False,
                   "allow_margin": False, "allow_short": False, "pdt_guard": False}
            s = size.size_trade(plan, cfg, today="2026-11-12")
            # The stop 1405.03 should be rounded down to 1405.0 (tick = 0.10)
            self.assertEqual(s["stop"], 1405.0)
            self.assertEqual(s["target"], 1427.5)
            self.assertEqual(s["bound_by"], "max loss")
            # Charges should be present on NSE and shrink the size
            self.assertIn("charges", s)
            self.assertGreater(s["charges"], 0)
            self.assertLess(s["qty"], size.shares_for(500, s["risk_per_share"]))
            order = size.bracket_order(s)
            self.assertIsNotNone(order)
            self.assertEqual(order["stop_loss_stop_price"], "1405.00")
            # Now run risk check on the same order, at an in-window time
            now_ist = "2026-11-12 10:00"
            res = check.check([order], cfg, prices={"RELIANCE": 1412.50},
                              today="2026-11-12", now=check.parse_now(now_ist))
            self.assertEqual(res["block"], 0, [r["reasons"] for r in res["results"]])
            r = res["results"][0]
            self.assertEqual(r["verdict"], "PASS")
            # Risk's numbers must match budget's
            self.assertEqual(r["risk_per_share"], s["risk_per_share"])
            self.assertEqual(r["max_loss"], s["max_loss"])
            # One more share should be blocked by the per-trade loss limit
            over_order = dict(order)
            over_order["qty"] = str(int(order["qty"]) + 1)
            over_res = check.check([over_order], cfg, prices={"RELIANCE": 1412.50},
                                   today="2026-11-12", now=check.parse_now(now_ist))
            over_r = over_res["results"][0]
            self.assertTrue(any(x.startswith("loss:") for x in over_r["reasons"]),
                            "expected loss: block with +1 share, got: %s" % over_r["reasons"])
        finally:
            size.use_market("us")
            check.use_market("us")

    def test_us_output_has_no_charges_fields(self):
        size = load("trader-budget", "size")
        plan = {"symbol": "TSLA", "side": "buy", "entry": 364.18,
                "stop": 358.32, "target": 370.04, "setup": "orb",
                "date": "2026-10-19", "entry_time": "10:15 AM", "flat_by": "15:55"}
        cfg = {"budget": 5000, "max_loss_per_trade_usd": 50,
               "max_order_usd": 4000, "max_position_pct": 75,
               "cash_buffer_pct": 10, "min_order_usd": 5,
               "max_daily_loss_usd": 150, "min_reward_risk": 1.0,
               "require_stop": True, "paper": True,
               "no_entries_before": "09:45", "no_entries_after": "15:30",
               "blocked": [], "allow_options": False,
               "allow_margin": False, "allow_short": False, "pdt_guard": False}
        s = size.size_trade(plan, cfg, today="2026-10-19")
        self.assertNotIn("charges", s)
        self.assertNotIn("max_loss_with_charges", s)
        self.assertNotIn("charges_breakdown", s)
        order = size.bracket_order(s)
        self.assertNotIn("charges", order["plan"])
        self.assertNotIn("max_loss_with_charges", order["plan"])


class TheUSDefaultIsUntouched(unittest.TestCase):
    def test_without_a_market_setting_the_tools_stay_on_new_york(self):
        old = os.getcwd()
        tmp = tempfile.mkdtemp()
        os.chdir(tmp)
        try:
            alerts = load("trader-alerts", "alerts")
            code, out, err = run(alerts, ["clock", "--now", "2026-10-19 10:15"])
            self.assertEqual(code, 0, out + err)
            self.assertIn("New York 2026-10-19 10:15", out)
            self.assertIn("NYSE OPEN", out)
            self.assertIn("09:30 to 16:00", out)
            self.assertEqual(alerts.MARKET, "us")
        finally:
            os.chdir(old)
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
