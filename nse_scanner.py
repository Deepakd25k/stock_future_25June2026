import os
import sys
import json
import time
import datetime
import requests
import io
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fii_historical_cache.json')

SECTOR_MAP = {
    'NIFTY AUTO':           ['ASHOKLEY','BALKRISIND','BHARATFORG','BOSCHLTD','EICHERMOT','HEROMOTOCO','M&M','MARUTI','MRF','MOTHERSON','TVSMOTOR','TIINDIA'],
    'NIFTY IT':             ['COFORGE','HCLTECH','INFY','LTIM','LTTS','MPHASIS','PERSISTENT','TCS','TECHM','WIPRO'],
    'NIFTY METAL':          ['HINDALCO','JINDALSTEL','JSWSTEEL','NATIONALUM','SAIL','TATASTEEL','VEDL','NMDC','HINDCOPPER'],
    'NIFTY BANK':           ['AUBANK','BANDHANBNK','FEDERALBNK','HDFCBANK','ICICIBANK','IDFCFIRSTB','INDUSINDB','KOTAKBANK','PNB','RBLBANK','SBIN'],
    'NIFTY FMCG':           ['BRITANNIA','COLPAL','DABUR','GODREJCP','HINDUNILVR','ITC','MARICO','NESTLEIND','TATACONSUM','UBL'],
    'NIFTY PHARMA':         ['ALKEM','APOLLOHOSP','AUROPHARMA','CIPLA','DIVISLAB','DRREDDY','LUPIN','TORNTPHARM','ZYDUSLIFE'],
    'NIFTY REALTY':         ['DLF','GODREJPROP','OBEROIRLTY','LODHA'],
    'NIFTY ENERGY':         ['BPCL','GAIL','HINDPETRO','IOC','NTPC','ONGC','POWERGRID','RELIANCE','TATAPOWER'],
    'NIFTY INFRASTRUCTURE': ['LT','ULTRACEMCO','GRASIM','ADANIPORTS','BHARTIARTL','GMRINFRA'],
}

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
}

# ─────────────────────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────────────────────
def init_nse_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1.5)
        s.get("https://www.nseindia.com/market-data/equity-derivatives-watch", timeout=10)
        time.sleep(1)
        return s
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# PARTICIPANT OI CSV PARSER — ALL COLUMNS
# ─────────────────────────────────────────────────────────────────────────────
def parse_participant_oi_csv(csv_text, date_formatted, date_key):
    """
    Parses ALL columns from NSE Participant OI CSV.
    Returns dict with FII, DII, Client, Pro data — futures + options.
    Source: archives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv
    """
    try:
        df = pd.read_csv(io.StringIO(csv_text), skiprows=1)
        df.columns = df.columns.str.strip()
        df['Client Type'] = df['Client Type'].str.strip()

        result = {"date_formatted": date_formatted, "date_key": date_key}

        for ptype in ['FII', 'DII', 'Client', 'Pro']:
            row = df[df['Client Type'] == ptype]
            if row.empty:
                continue
            r = row.iloc[0]
            prefix = ptype.lower()
            result[f'{prefix}_fut_idx_long']       = int(r.get('Future Index Long', 0))
            result[f'{prefix}_fut_idx_short']      = int(r.get('Future Index Short', 0))
            result[f'{prefix}_fut_stk_long']       = int(r.get('Future Stock Long', 0))
            result[f'{prefix}_fut_stk_short']      = int(r.get('Future Stock Short', 0))
            result[f'{prefix}_opt_idx_call_long']  = int(r.get('Option Index Call Long', 0))
            result[f'{prefix}_opt_idx_put_long']   = int(r.get('Option Index Put Long', 0))
            result[f'{prefix}_opt_idx_call_short'] = int(r.get('Option Index Call Short', 0))
            result[f'{prefix}_opt_idx_put_short']  = int(r.get('Option Index Put Short', 0))

        return result if len(result) > 2 else None
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# FII TREND — 5 DAYS WITH FULL PARTICIPANT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_fii_trend_data():
    """
    Fetches 5-day FII (and participant) OI trend.
    Calculates:
      - Futures: Index Net, Stock Net, day-over-day changes, action labels
      - Options: Net call/put positions for FII (directional intent)
      - DII vs FII divergence
      - Smart Money (FII+Pro) vs Dumb Money (Client) alignment
      - FII Dominance Ratio
      - OI Velocity (acceleration of change)
      - Commitment Ratio
      - Recovery Timeline
    """
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    utc_now = datetime.datetime.now(datetime.timezone.utc)
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    ist_mins = ist_now.hour * 60 + ist_now.minute

    successful_days = []
    for i in range(15):
        day_dt = ist_now - datetime.timedelta(days=i)
        date_key = day_dt.strftime("%d%m%Y")
        date_fmt = day_dt.strftime("%d-%b-%Y")

        if date_key in cache and 'fii_fut_idx_long' in cache[date_key]:
            successful_days.append(cache[date_key])
            if len(successful_days) == 5:
                break
            continue

        # Don't fetch today before 6:30 PM IST
        if i == 0 and ist_mins < 1110:
            continue

        url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{date_key}.csv"
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                parsed = parse_participant_oi_csv(r.text, date_fmt, date_key)
                if parsed:
                    cache[date_key] = parsed
                    successful_days.append(parsed)
                    if len(successful_days) == 5:
                        break
        except Exception:
            pass

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

    successful_days.sort(key=lambda x: datetime.datetime.strptime(x['date_key'], "%d%m%Y"))

    # Nifty price data
    nifty_map = {}
    try:
        nifty = yf.download("^NSEI", period="20d", progress=False)
        if not nifty.empty:
            if isinstance(nifty.columns, pd.MultiIndex):
                nifty.columns = nifty.columns.get_level_values(0)
            nifty['pct_change'] = nifty['Close'].pct_change() * 100
            for dt, row in nifty.iterrows():
                d_key = dt.strftime("%d%m%Y")
                nifty_map[d_key] = {
                    "nifty_close": float(row['Close']),
                    "nifty_change": float(row['pct_change']) if not pd.isna(row['pct_change']) else 0.0
                }
    except Exception:
        pass

    # Compute derived metrics for each day
    for idx, day in enumerate(successful_days):
        # ── Futures Net positions ──
        day['fii_fut_idx_net']  = day.get('fii_fut_idx_long', 0) - day.get('fii_fut_idx_short', 0)
        day['fii_fut_stk_net']  = day.get('fii_fut_stk_long', 0) - day.get('fii_fut_stk_short', 0)
        day['dii_fut_idx_net']  = day.get('dii_fut_idx_long', 0) - day.get('dii_fut_idx_short', 0)
        day['dii_fut_stk_net']  = day.get('dii_fut_stk_long', 0) - day.get('dii_fut_stk_short', 0)
        day['client_fut_idx_net'] = day.get('client_fut_idx_long', 0) - day.get('client_fut_idx_short', 0)
        day['client_fut_stk_net'] = day.get('client_fut_stk_long', 0) - day.get('client_fut_stk_short', 0)
        day['pro_fut_idx_net']    = day.get('pro_fut_idx_long', 0) - day.get('pro_fut_idx_short', 0)
        day['pro_fut_stk_net']    = day.get('pro_fut_stk_long', 0) - day.get('pro_fut_stk_short', 0)

        # ── FII Options: Net Calls - Net Puts (Index) ──
        # Positive = FII net long calls (bullish directional) 
        # Negative = FII net long puts (bearish directional)
        fii_net_calls = day.get('fii_opt_idx_call_long', 0) - day.get('fii_opt_idx_call_short', 0)
        fii_net_puts  = day.get('fii_opt_idx_put_long', 0)  - day.get('fii_opt_idx_put_short', 0)
        day['fii_opt_idx_net_calls'] = fii_net_calls   # positive = bullish
        day['fii_opt_idx_net_puts']  = fii_net_puts    # positive = bearish hedge
        # Combined options signal: calls - puts (net directional)
        day['fii_opt_idx_directional'] = fii_net_calls - fii_net_puts

        # ── FII Commitment Ratio (Index) ──
        fii_idx_total = day.get('fii_fut_idx_long', 0) + day.get('fii_fut_idx_short', 0)
        day['fii_idx_commitment'] = round(abs(day['fii_fut_idx_net']) / fii_idx_total * 100, 1) if fii_idx_total > 0 else 0

        # ── FII Index L/S Ratio ──
        day['index_ratio'] = round(day.get('fii_fut_idx_long', 0) / fii_idx_total * 100, 1) if fii_idx_total > 0 else 0
        fii_stk_total = day.get('fii_fut_stk_long', 0) + day.get('fii_fut_stk_short', 0)
        day['stock_ratio'] = round(day.get('fii_fut_stk_long', 0) / fii_stk_total * 100, 1) if fii_stk_total > 0 else 0

        # ── Smart Money vs Dumb Money ──
        # Smart Money = FII + Pro (net futures stock)
        day['smart_money_stk'] = day['fii_fut_stk_net'] + day['pro_fut_stk_net']
        day['dumb_money_stk']  = day['client_fut_stk_net']
        if (day['smart_money_stk'] > 0 and day['dumb_money_stk'] < 0):
            day['smart_vs_dumb'] = "SMART_BUY_DUMB_SELL"   # Best buy signal
        elif (day['smart_money_stk'] < 0 and day['dumb_money_stk'] > 0):
            day['smart_vs_dumb'] = "SMART_SELL_DUMB_BUY"   # Distribution trap
        elif (day['smart_money_stk'] > 0 and day['dumb_money_stk'] > 0):
            day['smart_vs_dumb'] = "BOTH_BUYING"            # Crowded, careful
        else:
            day['smart_vs_dumb'] = "BOTH_SELLING"           # Crash risk

        # ── DII behaviour ──
        day['dii_behaviour'] = "SUPPORTING" if day['dii_fut_stk_net'] > 0 else "SELLING"

        # ── Nifty price mapping ──
        if day['date_key'] in nifty_map:
            day['nifty_close']  = nifty_map[day['date_key']]['nifty_close']
            day['nifty_change'] = nifty_map[day['date_key']]['nifty_change']
        else:
            day['nifty_close']  = None
            day['nifty_change'] = None

        # ── Day-over-day changes ──
        if idx == 0:
            day['fii_fut_idx_net_chg'] = 0
            day['fii_fut_stk_net_chg'] = 0
            day['fii_opt_idx_dir_chg'] = 0
            day['fii_idx_commit_chg']  = 0
        else:
            prev = successful_days[idx - 1]
            day['fii_fut_idx_net_chg'] = day['fii_fut_idx_net'] - prev['fii_fut_idx_net']
            day['fii_fut_stk_net_chg'] = day['fii_fut_stk_net'] - prev['fii_fut_stk_net']
            day['fii_opt_idx_dir_chg'] = day['fii_opt_idx_directional'] - prev['fii_opt_idx_directional']
            day['fii_idx_commit_chg']  = day['fii_idx_commitment'] - prev['fii_idx_commitment']

    # ── OI Velocity (acceleration of stock net change) ──
    for idx, day in enumerate(successful_days):
        if idx < 2:
            day['stk_velocity'] = 0
        else:
            prev_chg      = successful_days[idx-1]['fii_fut_stk_net_chg']
            curr_chg      = day['fii_fut_stk_net_chg']
            day['stk_velocity'] = curr_chg - prev_chg  # positive = accelerating

    # ── Action Labels for FII Futures ──
    for idx, day in enumerate(successful_days):
        if idx == 0:
            day['index_action'] = "Neutral"
            day['stock_action'] = "Neutral"
            continue
        prev = successful_days[idx - 1]

        # Index action
        ic  = day['fii_fut_idx_net_chg']
        ilc = day.get('fii_fut_idx_long', 0) - prev.get('fii_fut_idx_long', 0)
        isc = day.get('fii_fut_idx_short', 0) - prev.get('fii_fut_idx_short', 0)
        if ic > 0:
            if ilc > abs(isc) * 1.5 and ilc > 4000:
                day['index_action'] = "Aggressive Buying"
            elif isc < -4000 and ilc >= 0:
                day['index_action'] = "Short Covering"
            elif idx >= 2 and successful_days[idx-1].get('fii_fut_idx_net_chg', 0) > 0:
                day['index_action'] = "Accumulating"
            else:
                day['index_action'] = "Initial Buying"
        else:
            if isc > abs(ilc) * 1.5 and isc > 4000:
                day['index_action'] = "Aggressive Shorting"
            elif ilc < -4000 and isc <= 0:
                day['index_action'] = "Long Unwinding"
            else:
                day['index_action'] = "Profit Booking"

        # Stock action
        sc  = day['fii_fut_stk_net_chg']
        slc = day.get('fii_fut_stk_long', 0) - prev.get('fii_fut_stk_long', 0)
        ssc = day.get('fii_fut_stk_short', 0) - prev.get('fii_fut_stk_short', 0)
        if sc > 0:
            if slc > abs(ssc) * 1.5 and slc > 15000:
                day['stock_action'] = "Aggressive Buying"
            elif ssc < -15000 and slc >= 0:
                day['stock_action'] = "Short Covering"
            elif idx >= 2 and successful_days[idx-1].get('fii_fut_stk_net_chg', 0) > 0:
                day['stock_action'] = "Accumulating"
            else:
                day['stock_action'] = "Initial Buying"
        else:
            if ssc > abs(slc) * 1.5 and ssc > 15000:
                day['stock_action'] = "Aggressive Shorting"
            elif slc < -15000 and ssc <= 0:
                day['stock_action'] = "Long Unwinding"
            else:
                day['stock_action'] = "Profit Booking"

    # ── Recovery Timeline ──
    if len(successful_days) >= 2:
        last = successful_days[-1]
        # Total net sold in last 3 bearish days
        bearish_days = [d for d in successful_days if d.get('fii_fut_stk_net_chg', 0) < 0]
        total_sold = abs(sum(d['fii_fut_stk_net_chg'] for d in bearish_days))
        daily_buy_rate = last['fii_fut_stk_net_chg'] if last['fii_fut_stk_net_chg'] > 0 else 0
        if daily_buy_rate > 0 and total_sold > 0:
            recovery_days = round(total_sold / daily_buy_rate, 1)
        else:
            recovery_days = None
        successful_days[-1]['recovery_days'] = recovery_days

    return successful_days


# ─────────────────────────────────────────────────────────────────────────────
# MORNING BRIEFING — DECISION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def compute_morning_briefing(fii_trend, global_signals, vix):
    """
    Generates trade decision from verified data:
      - FII Futures direction (NSE official)
      - FII Options directional signal (NSE official)
      - Smart vs Dumb Money alignment (NSE official)
      - Global signals: S&P500, USD/INR (yfinance)
      - VIX (NSE official)
    """
    if not fii_trend or len(fii_trend) < 2:
        return None

    last = fii_trend[-1]
    prev = fii_trend[-2]

    # ── Futures direction ──
    stk_chg = last.get('fii_fut_stk_net_chg', 0)
    idx_chg = last.get('fii_fut_idx_net_chg', 0)
    stk_pos = "positive" if stk_chg > 5000 else "negative" if stk_chg < -5000 else "neutral"
    idx_pos = "positive" if idx_chg > 2000 else "negative" if idx_chg < -2000 else "neutral"

    # ── Options signal ──
    opt_dir = last.get('fii_opt_idx_directional', 0)
    opt_signal = "bullish" if opt_dir > 10000 else "bearish" if opt_dir < -10000 else "neutral"

    # ── Consecutive days ──
    consecutive = 0
    direction = 1 if stk_chg >= 0 else -1
    for d in reversed(fii_trend):
        if d.get('fii_fut_stk_net_chg', 0) * direction >= 0:
            consecutive += 1
        else:
            break

    # ── Commitment trend ──
    commit_trend = "increasing" if last.get('fii_idx_commit_chg', 0) > 0 else "decreasing"

    # ── Smart vs Dumb ──
    svd = last.get('smart_vs_dumb', '')
    dii  = last.get('dii_behaviour', '')

    # ── VIX interpretation ──
    vix_val = vix.get('last', 15) if vix else 15
    if vix_val < 14:
        vix_status = "LOW"
        vix_note   = "Trade freely"
    elif vix_val < 18:
        vix_status = "MEDIUM"
        vix_note   = "Trade cautiously"
    else:
        vix_status = "HIGH"
        vix_note   = "Avoid or very small position"

    # ── Global context ──
    sp500_chg  = global_signals.get('sp500_chg', 0)
    usdinr_chg = global_signals.get('usdinr_chg', 0)
    # Rupee strengthening (usdinr_chg < 0) = FII comfortable
    global_bias = "positive" if (sp500_chg > 0 and usdinr_chg < 0) else \
                  "negative" if (sp500_chg < 0 and usdinr_chg > 0) else "mixed"

    # ── Trade decisions ──
    if stk_pos == "positive" and idx_pos == "positive":
        trade_what = "BOTH"
        direction_label = "LONG"
        reason = "FII buying both index shorts cover and stocks"
    elif stk_pos == "positive" and idx_pos != "positive":
        trade_what = "STOCKS_ONLY"
        direction_label = "LONG"
        reason = "FII accumulating stocks, index is hedge adjustment"
    elif stk_pos == "negative" and idx_pos == "negative":
        trade_what = "INDEX_SHORT"
        direction_label = "SHORT"
        reason = "FII selling both — short index, no stock longs"
    elif stk_pos == "negative" and idx_pos == "positive":
        trade_what = "AVOID"
        direction_label = "WAIT"
        reason = "Divergence — conflicting signals, wait for clarity"
    else:
        trade_what = "NEUTRAL"
        direction_label = "WAIT"
        reason = "No strong signal today"

    # ── Velocity insight ──
    vel = last.get('stk_velocity', 0)
    if vel > 5000:
        velocity_note = "Accelerating — conviction building rapidly"
    elif vel < -5000:
        velocity_note = "Decelerating — reversal may be near"
    else:
        velocity_note = "Steady pace"

    # ── Abnormal pattern detection ──
    alerts = []
    stk_net = last.get('fii_fut_stk_net', 0)
    if stk_net < 0:
        alerts.append("⚠️ FII Stock Net NEGATIVE — extremely rare, high caution")
    if last.get('index_ratio', 15) > 35:
        alerts.append("🚨 FII Index L/S ratio unusually high — major short covering rally possible")
    if svd == "SMART_BUY_DUMB_SELL":
        alerts.append("✅ Smart Money buying while retail panicking — best entry setup")
    elif svd == "SMART_SELL_DUMB_BUY":
        alerts.append("🔴 Smart Money selling while retail FOMO buying — distribution trap")
    if opt_signal == "bullish" and direction_label == "LONG":
        alerts.append("✅ FII Options confirm: buying Nifty calls — real directional conviction")
    elif opt_signal == "bearish" and direction_label == "LONG":
        alerts.append("⚠️ FII Options conflict: buying puts despite futures bullish — hedge not conviction")

    return {
        "trade_what": trade_what,
        "direction": direction_label,
        "reason": reason,
        "stk_pos": stk_pos,
        "idx_pos": idx_pos,
        "opt_signal": opt_signal,
        "consecutive_days": consecutive,
        "commit_trend": commit_trend,
        "velocity_note": velocity_note,
        "vix": vix_val,
        "vix_status": vix_status,
        "vix_note": vix_note,
        "global_bias": global_bias,
        "sp500_chg": sp500_chg,
        "usdinr_chg": usdinr_chg,
        "smart_vs_dumb": svd,
        "dii_behaviour": dii,
        "alerts": alerts,
        "recovery_days": last.get('recovery_days'),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL SIGNALS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_global_signals():
    """Fetches S&P500, USD/INR, Nifty, BankNifty from yfinance."""
    result = {}
    tickers = {
        'sp500':     '^GSPC',
        'usdinr':    'USDINR=X',
        'nifty':     '^NSEI',
        'banknifty': '^NSEBANK',
    }
    try:
        syms = list(tickers.values())
        data = yf.download(" ".join(syms), period="5d", progress=False)
        if data.empty:
            return result
        close = data['Close'] if not isinstance(data.columns, pd.MultiIndex) else data['Close']

        for name, sym in tickers.items():
            try:
                col = sym if sym in close.columns else None
                if col is None:
                    continue
                last_p = float(close[col].dropna().iloc[-1])
                prev_p = float(close[col].dropna().iloc[-2])
                chg    = (last_p - prev_p) / prev_p * 100
                result[f'{name}_last'] = round(last_p, 2)
                result[f'{name}_chg']  = round(chg, 2)
            except Exception:
                pass
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# INDIA VIX
# ─────────────────────────────────────────────────────────────────────────────
def fetch_india_vix(session):
    """Fetches India VIX from NSE allIndices API."""
    try:
        r = session.get(
            "https://www.nseindia.com/api/allIndices",
            headers={"Referer": "https://www.nseindia.com/market-data/live-market-indices"},
            timeout=10
        )
        if r.status_code == 200:
            for item in r.json().get('data', []):
                if item.get('index') == 'INDIA VIX':
                    return {
                        'last':    item.get('last', 0),
                        'change':  item.get('variation', 0),
                        'pct_chg': item.get('percentChange', 0),
                    }
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SECTOR PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────
def fetch_sector_data(session):
    """Fetches all NSE sector indices performance."""
    try:
        r = session.get(
            "https://www.nseindia.com/api/allIndices",
            headers={"Referer": "https://www.nseindia.com/market-data/live-market-indices"},
            timeout=10
        )
        if r.status_code != 200:
            return None
        sectors = []
        for item in r.json().get('data', []):
            if item.get('index') in SECTOR_MAP:
                adv = int(item.get('advances', 0))
                dec = int(item.get('declines', 0))
                tot = adv + dec
                sectors.append({
                    'index':    item['index'],
                    'change':   float(item.get('percentChange', 0)),
                    'advances': adv,
                    'declines': dec,
                    'breadth':  round(adv / tot * 100, 1) if tot > 0 else 0,
                })
        return pd.DataFrame(sectors).sort_values('change', ascending=False) if sectors else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# OI SPURTS (all stocks)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_nse_oi_spurts(session):
    try:
        r = session.get(
            "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings",
            headers={"Referer": "https://www.nseindia.com/market-data/equity-derivatives-watch"},
            timeout=10
        )
        if r.status_code != 200:
            return None
        items = []
        for item in r.json().get('data', []):
            items.append({
                'symbol':     item.get('symbol'),
                'oi_chg_pct': float(item.get('avgInOI', 0)),
                'volume':     int(item.get('volume', 0)),
                'fut_value':  float(item.get('futValue', 0)) / 100,
                'ltp':        float(item.get('underlyingValue', 0)),
            })
        return pd.DataFrame(items)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ATR CALCULATION (Wilder, 1978)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_atr_and_levels(symbols, period=14):
    """
    Calculates ATR(14) using Wilder's True Range formula.
    Returns stop loss (Entry - 1.5×ATR) and target (Entry + 2×Risk).
    Data source: yfinance (OHLCV).
    """
    result = {}
    for sym in symbols:
        try:
            d = yf.download(f"{sym}.NS", period="40d", progress=False)
            if d.empty:
                continue
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            d = d.dropna()
            if len(d) < period + 1:
                continue
            d['prev_close'] = d['Close'].shift(1)
            d['tr'] = d.apply(lambda r: max(
                r['High'] - r['Low'],
                abs(r['High'] - r['prev_close']),
                abs(r['Low']  - r['prev_close'])
            ), axis=1)
            atr = float(d['tr'].rolling(period).mean().dropna().iloc[-1])
            ltp = float(d['Close'].iloc[-1])
            stop   = round(ltp - 1.5 * atr, 2)
            risk   = ltp - stop
            target1 = round(ltp + 2.0 * risk, 2)
            target2 = round(ltp + 3.0 * risk, 2)
            result[sym] = {
                'ltp':     round(ltp, 2),
                'atr':     round(atr, 2),
                'stop':    stop,
                'target1': target1,
                'target2': target2,
                'risk_pct': round(risk / ltp * 100, 2),
            }
        except Exception:
            pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# BLOCK DEALS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_block_deals(session):
    """Fetches block deal data from NSE (official daily report)."""
    try:
        r = session.get(
            "https://www.nseindia.com/api/block-deal",
            headers={"Referer": "https://www.nseindia.com/market-data/block-deal"},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            deals = data.get('data', []) + data.get('Session 2', [])
            result = []
            for d in deals:
                val_cr = d.get('totalTradedValue', 0) / 1e7  # paise to crores
                result.append({
                    'symbol':   d.get('symbol', ''),
                    'price':    d.get('lastPrice', 0),
                    'change':   d.get('pchange', 0),
                    'volume':   d.get('totalTradedVolume', 0),
                    'value_cr': round(val_cr, 1),
                    'session':  d.get('session', 'S1'),
                })
            return sorted(result, key=lambda x: x['value_cr'], reverse=True)
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRY CALENDAR
# ─────────────────────────────────────────────────────────────────────────────
def get_expiry_context():
    """
    Returns current expiry week context.
    NSE F&O expiry = last Thursday of each month.
    """
    import calendar
    today = datetime.date.today()

    def last_thursday(year, month):
        last_day = calendar.monthrange(year, month)[1]
        return max(
            datetime.date(year, month, d)
            for d in range(1, last_day + 1)
            if datetime.date(year, month, d).weekday() == 3
        )

    year, month = today.year, today.month
    last_thu = last_thursday(year, month)
    days_to_expiry = (last_thu - today).days
    if days_to_expiry < 0:
        next_month = month % 12 + 1
        next_year  = year + (1 if month == 12 else 0)
        last_thu   = last_thursday(next_year, next_month)
        days_to_expiry = (last_thu - today).days

    if days_to_expiry <= 2:
        week = "EXPIRY"
        note = "Last 2 days — avoid new positions, OI squaring off"
        caution = "HIGH"
    elif days_to_expiry <= 7:
        week = "EXPIRY_WEEK"
        note = "Expiry week — reduce position sizes, use options"
        caution = "MEDIUM"
    elif days_to_expiry >= 20:
        week = "WEEK_1"
        note = "Fresh month — FIIs building new positions, good for trend trades"
        caution = "LOW"
    else:
        week = "MID_MONTH"
        note = "Mid month — trending moves strongest here"
        caution = "LOW"

    return {
        "expiry_date":     last_thu.strftime("%d-%b-%Y"),
        "days_to_expiry":  days_to_expiry,
        "week_label":      week,
        "note":            note,
        "caution":         caution,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STOCK SELECTION — ALL SECTORS SCAN
# ─────────────────────────────────────────────────────────────────────────────
def build_stock_universe(oi_df, sectors_df, briefing):
    """
    Scans ALL sector stocks for Long/Short Buildup.
    Ranks by momentum score = price_chg × oi_chg.
    Filters: value > 500 Cr, buildup type matches FII direction.
    Returns top 5 stocks with ATR levels.
    """
    if oi_df is None or oi_df.empty:
        return []

    direction = briefing.get('direction', 'LONG') if briefing else 'LONG'
    all_symbols = list(set(sym for syms in SECTOR_MAP.values() for sym in syms))
    index_syms  = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'}
    all_symbols = [s for s in all_symbols if s not in index_syms]

    # Price data from yfinance
    price_map = {}
    try:
        yf_syms = [f"{s}.NS" for s in all_symbols]
        d = yf.download(" ".join(yf_syms), period="5d", progress=False)
        if not d.empty:
            close = d['Close'] if not isinstance(d.columns, pd.MultiIndex) else d['Close']
            for s in all_symbols:
                ys = f"{s}.NS"
                if ys not in close.columns:
                    continue
                col = close[ys].dropna()
                if len(col) < 2:
                    continue
                lp = float(col.iloc[-1])
                pp = float(col.iloc[-2])
                price_map[s] = {'price': lp, 'chg': (lp - pp) / pp * 100}
    except Exception:
        pass

    stocks = []
    for sym in all_symbols:
        oi_row = oi_df[oi_df['symbol'] == sym]
        oi_chg = float(oi_row.iloc[0]['oi_chg_pct']) if not oi_row.empty else 0
        val_cr = float(oi_row.iloc[0]['fut_value'])   if not oi_row.empty else 0

        pd_info   = price_map.get(sym, {})
        price_chg = pd_info.get('chg', 0)
        ltp       = pd_info.get('price', 0)

        # Buildup classification (NSE standard)
        if price_chg > 0.1 and oi_chg > 1.0:
            buildup = "Long Buildup"
        elif price_chg < -0.1 and oi_chg > 1.0:
            buildup = "Short Buildup"
        elif price_chg > 0.1 and oi_chg < -1.0:
            buildup = "Short Covering"
        elif price_chg < -0.1 and oi_chg < -1.0:
            buildup = "Long Unwinding"
        else:
            buildup = "Neutral"

        momentum = abs(price_chg * oi_chg)

        # Sector lookup
        sector = next((k for k, v in SECTOR_MAP.items() if sym in v), "")

        stocks.append({
            'symbol':    sym,
            'sector':    sector,
            'ltp':       round(ltp, 2),
            'price_chg': round(price_chg, 2),
            'oi_chg':    round(oi_chg, 2),
            'buildup':   buildup,
            'momentum':  round(momentum, 2),
            'value_cr':  round(val_cr, 1),
        })

    # Filter by direction and liquidity
    target_buildup = "Long Buildup" if direction in ("LONG", "BOTH") else "Short Buildup"
    filtered = [s for s in stocks if s['buildup'] == target_buildup and s['value_cr'] >= 500]
    filtered.sort(key=lambda x: x['momentum'], reverse=True)
    top = filtered[:5]

    # Fetch ATR levels for top picks
    atr_data = fetch_atr_and_levels([s['symbol'] for s in top])
    for s in top:
        atr = atr_data.get(s['symbol'], {})
        s['stop']    = atr.get('stop')
        s['target1'] = atr.get('target1')
        s['target2'] = atr.get('target2')
        s['atr']     = atr.get('atr')
        s['risk_pct']= atr.get('risk_pct')

    return top


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCAN
# ─────────────────────────────────────────────────────────────────────────────
def run_scan():
    session = init_nse_session()
    if not session:
        return {"error": "Cannot connect to NSE"}

    # Parallel-ish fetches
    vix         = fetch_india_vix(session)
    sectors_df  = fetch_sector_data(session)
    oi_df       = fetch_nse_oi_spurts(session)
    block_deals = fetch_block_deals(session)
    fii_trend   = fetch_fii_trend_data()
    global_sig  = fetch_global_signals()
    expiry_ctx  = get_expiry_context()
    briefing    = compute_morning_briefing(fii_trend, global_sig, vix)
    top_stocks  = build_stock_universe(oi_df, sectors_df, briefing)

    # Which index to trade
    index_to_trade = "Nifty 50"
    if sectors_df is not None and not sectors_df.empty:
        top_sec = sectors_df.iloc[0]['index']
        if top_sec == 'NIFTY BANK':
            index_to_trade = "Bank Nifty"
        elif top_sec in ('NIFTY IT', 'NIFTY AUTO', 'NIFTY METAL'):
            index_to_trade = "Nifty 50"
    if briefing:
        briefing['index_to_trade'] = index_to_trade

    def clean(lst):
        clean_lst = []
        for rec in lst:
            c = {}
            for k, v in (rec.items() if isinstance(rec, dict) else rec.to_dict().items()):
                c[k] = None if (isinstance(v, float) and pd.isna(v)) else v
            clean_lst.append(c)
        return clean_lst

    return {
        "success":     True,
        "timestamp":   (datetime.datetime.now(datetime.timezone.utc) +
                        datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST"),
        "fii_trend":   fii_trend,
        "briefing":    briefing,
        "vix":         vix,
        "global":      global_sig,
        "expiry":      expiry_ctx,
        "top_stocks":  top_stocks,
        "block_deals": block_deals[:8],
        "sectors":     clean(sectors_df.to_dict(orient='records')) if sectors_df is not None else [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI DISPLAY
# ─────────────────────────────────────────────────────────────────────────────
def print_cli_results(result):
    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        return

    console.print(Panel("[bold green]SmartMoney — NSE F&O Intelligence Dashboard[/bold green]",
                        subtitle="FII + Participant OI Analysis"))

    # ── Morning Briefing ──
    b = result.get('briefing', {})
    if b:
        console.print("\n[bold yellow]═══ MORNING BRIEFING ═══[/bold yellow]")
        vix = result.get('vix', {})
        g   = result.get('global', {})
        console.print(f"  India VIX : [bold]{vix.get('last','N/A')}[/bold]  ({b.get('vix_status')}) — {b.get('vix_note')}")
        console.print(f"  S&P 500   : {g.get('sp500_chg',0):+.2f}%   USD/INR: {g.get('usdinr_chg',0):+.2f}%   Global: {b.get('global_bias','').upper()}")
        console.print(f"  Smart/Dumb: {b.get('smart_vs_dumb','N/A')}   DII: {b.get('dii_behaviour','N/A')}")
        exp = result.get('expiry', {})
        console.print(f"  Expiry    : {exp.get('expiry_date')} ({exp.get('days_to_expiry')} days) — {exp.get('note')}")
        console.print(f"\n  [bold]DECISION: {b.get('trade_what')} — {b.get('direction')}[/bold]")
        console.print(f"  Index: [cyan]{b.get('index_to_trade')}[/cyan]   Consecutive days: {b.get('consecutive_days')}   Velocity: {b.get('velocity_note')}")
        console.print(f"  FII Options Signal: [bold]{b.get('opt_signal','').upper()}[/bold]")
        for alert in b.get('alerts', []):
            console.print(f"  {alert}")
        if b.get('recovery_days'):
            console.print(f"  Recovery timeline: ~{b.get('recovery_days')} trading days to recover sold OI")

    # ── FII Trend Table ──
    console.print()
    t = Table(title="🏛️ FII Participant OI Trend (5 Days)")
    for col in ["Date","Nifty","Fut Idx Net(Chg)","Action","Fut Stk Net(Chg)","Action","Opt Idx Dir","Smart/Dumb","Commit%"]:
        t.add_column(col, justify="right" if col not in ("Action","Smart/Dumb") else "left")
    for d in result['fii_trend']:
        nifty_s = f"{d.get('nifty_close',0):,.0f} ({d.get('nifty_change',0):+.2f}%)" if d.get('nifty_close') else "N/A"
        ic  = d.get('fii_fut_idx_net_chg', 0)
        sc  = d.get('fii_fut_stk_net_chg', 0)
        opt = d.get('fii_opt_idx_directional', 0)
        ic_col = "green" if ic > 0 else "red" if ic < 0 else "white"
        sc_col = "green" if sc > 0 else "red" if sc < 0 else "white"
        t.add_row(
            d.get('date_formatted',''),
            nifty_s,
            f"[{ic_col}]{d.get('fii_fut_idx_net',0):+,} ({ic:+,})[/{ic_col}]",
            d.get('index_action',''),
            f"[{sc_col}]{d.get('fii_fut_stk_net',0):+,} ({sc:+,})[/{sc_col}]",
            d.get('stock_action',''),
            f"{opt:+,}",
            d.get('smart_vs_dumb','')[:18],
            f"{d.get('fii_idx_commitment',0):.1f}%",
        )
    console.print(t)

    # ── Top Stocks ──
    console.print("\n[bold gold3]═══ TOP STOCKS FOR TOMORROW ═══[/bold gold3]")
    for i, s in enumerate(result.get('top_stocks', []), 1):
        console.print(f"  {i}. [bold]{s['symbol']}[/bold] ({s['sector']}) — {s['buildup']}")
        console.print(f"     LTP: ₹{s['ltp']:,.2f}  Price: {s['price_chg']:+.2f}%  OI: {s['oi_chg']:+.2f}%  Value: {s['value_cr']:.0f}Cr")
        if s.get('stop'):
            console.print(f"     Stop: ₹{s['stop']:,.2f}  Target1: ₹{s['target1']:,.2f}  Target2: ₹{s['target2']:,.2f}  ATR: {s['atr']:.2f}")

    # ── Block Deals ──
    if result.get('block_deals'):
        console.print("\n[bold cyan]═══ BLOCK DEALS (NSE Official) ═══[/bold cyan]")
        for bd in result['block_deals'][:5]:
            console.print(f"  {bd['symbol']:<15} ₹{bd['price']:>8,.2f}  Chg:{bd['change']:>+6.2f}%  Value:₹{bd['value_cr']:.0f}Cr")


if __name__ == "__main__":
    result = run_scan()
    print_cli_results(result)
