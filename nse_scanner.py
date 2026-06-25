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
from rich.text import Text

# Initialize Rich Console for beautiful terminal formatting
console = Console()

# Cache file path for FII historical trend
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fii_historical_cache.json')

# Sector to F&O Constituents Map (Hardcoded for high stability and speed)
SECTOR_MAP = {
    'NIFTY AUTO': ['ASHOKLEY', 'BALKRISIND', 'BHARATFORG', 'BOSCHLTD', 'EICHERMOT', 'HEROMOTOCO', 'M&M', 'MARUTI', 'MRF', 'MOTHERSON', 'TATAMOTORS', 'TVSMOTOR', 'TIINDIA'],
    'NIFTY IT': ['COFORGE', 'HCLTECH', 'INFY', 'LTIM', 'LTTS', 'MPHASIS', 'PERSISTENT', 'TCS', 'TECHM', 'WIPRO'],
    'NIFTY METAL': ['HINDALCO', 'JINDALSTEL', 'JSWSTEEL', 'NATIONALUM', 'SAIL', 'TATASTEEL', 'VEDL', 'NMDC', 'HINDCOPPER'],
    'NIFTY BANK': ['AUBANK', 'BANDHANBNK', 'FEDERALBNK', 'HDFCBANK', 'ICICIBANK', 'IDFCFIRSTB', 'INDUSINDB', 'KOTAKBANK', 'PNB', 'RBLBANK', 'SBIN'],
    'NIFTY FMCG': ['BRITANNIA', 'COLPAL', 'DABUR', 'GODREJCP', 'HINDUNILVR', 'ITC', 'MARICO', 'NESTLEIND', 'TATACONSUM', 'UBL', 'MCDOWELL-N'],
    'NIFTY PHARMA': ['ABBOTINDIA', 'ALKEM', 'APOLLOHOSP', 'AUROPHARMA', 'BIOCON', 'CIPLA', 'DIVISLAB', 'DRREDDY', 'IPCALAB', 'LAURUSLABS', 'LUPIN', 'GLENMARK', 'GRANULES', 'SYNGENE', 'TORNTPHARM', 'ZYDUSLIFE'],
    'NIFTY REALTY': ['DLF', 'GODREJPROP', 'OBEROIRLTY', 'LODHA'],
    'NIFTY ENERGY': ['BPCL', 'GAIL', 'HINDPETRO', 'IOC', 'NTPC', 'ONGC', 'POWERGRID', 'RELIANCE', 'TATAPOWER'],
    'NIFTY INFRASTRUCTURE': ['LT', 'NTPC', 'ONGC', 'POWERGRID', 'RELIANCE', 'TATAPOWER', 'ULTRACEMCO', 'GRASIM', 'ADANIPORTS', 'BHARTIARTL', 'GMRINFRA', 'IRB']
}

# Browser headers to fetch NSE data without 403 blocks
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-US,en;q=0.9,en-IN;q=0.8,en-GB;q=0.7",
    "cache-control": "max-age=0",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
}

def init_nse_session():
    """Initializes requests session and fetches homepage to gather cookies."""
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1.5)
        s.get("https://www.nseindia.com/market-data/equity-derivatives-watch", timeout=10)
        time.sleep(1)
        return s
    except Exception as e:
        return None

def fetch_top_sector(session):
    """Fetches all indices and ranks them to find the top outperforming sector."""
    url = "https://www.nseindia.com/api/allIndices"
    referer = "https://www.nseindia.com/market-data/live-market-indices"
    try:
        r = session.get(url, headers={"Referer": referer}, timeout=10)
        if r.status_code != 200:
            return None
        
        data = r.json()
        valid_sectors = list(SECTOR_MAP.keys())
        sector_data = []
        
        for item in data.get('data', []):
            idx_name = item.get('index')
            if idx_name in valid_sectors:
                adv = int(item.get('advances', 0))
                dec = int(item.get('declines', 0))
                total = adv + dec
                breadth = (adv / total) * 100 if total > 0 else 0
                
                sector_data.append({
                    'index': idx_name,
                    'change': float(item.get('percentChange', 0.0)),
                    'advances': adv,
                    'declines': dec,
                    'breadth': breadth
                })
        
        sector_df = pd.DataFrame(sector_data).sort_values(by='change', ascending=False)
        return sector_df
    except Exception as e:
        return None

def fetch_nse_oi_spurts(session):
    """Fetches F&O Open Interest data for all underlyings."""
    url = "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings"
    referer = "https://www.nseindia.com/market-data/equity-derivatives-watch"
    try:
        r = session.get(url, headers={"Referer": referer}, timeout=10)
        if r.status_code != 200:
            return None
        
        data = r.json()
        oi_list = []
        for item in data.get('data', []):
            oi_list.append({
                'symbol': item.get('symbol'),
                'oi_change': float(item.get('avgInOI', 0.0)),
                'volume': int(item.get('volume', 0)),
                'fut_value': float(item.get('futValue', 0.0)) / 100.0, # Convert Lakhs to Crores
                'ltp_nse': float(item.get('underlyingValue', 0.0))
            })
        return pd.DataFrame(oi_list)
    except Exception as e:
        return None

def fetch_yfinance_prices(symbols):
    """Fetches live stock price changes from Yahoo Finance using yfinance download."""
    yf_symbols = [f"{sym}.NS" for sym in symbols]
    try:
        data = yf.download(" ".join(yf_symbols), period="5d", progress=False)
        if data.empty or 'Close' not in data:
            return {}
        
        close_data = data['Close']
        if isinstance(close_data, pd.Series):
            close_data = pd.DataFrame({yf_symbols[0]: close_data})
            
        last_row = close_data.iloc[-1]
        prev_row = close_data.iloc[-2]
        
        price_map = {}
        for yf_sym in yf_symbols:
            nse_sym = yf_sym.replace(".NS", "")
            try:
                last_price = last_row[yf_sym]
                prev_price = prev_row[yf_sym]
                if pd.isna(last_price) or pd.isna(prev_price):
                    price_map[nse_sym] = {'price': None, 'change': None}
                else:
                    pct_change = ((last_price - prev_price) / prev_price) * 100
                    price_map[nse_sym] = {'price': last_price, 'change': pct_change}
            except KeyError:
                price_map[nse_sym] = {'price': None, 'change': None}
        return price_map
    except Exception as e:
        return {}

def parse_fii_oi_csv(csv_text, date_formatted, date_key):
    """Parses FII Open Interest data from the downloaded CSV text."""
    try:
        # Read CSV skipping the first row (Participant Open Interest...)
        df = pd.read_csv(io.StringIO(csv_text), skiprows=1)
        df.columns = df.columns.str.strip()
        df['Client Type'] = df['Client Type'].str.strip()
        
        fii_row = df[df['Client Type'] == 'FII']
        if not fii_row.empty:
            idx_long = int(fii_row.iloc[0]['Future Index Long'])
            idx_short = int(fii_row.iloc[0]['Future Index Short'])
            stk_long = int(fii_row.iloc[0]['Future Stock Long'])
            stk_short = int(fii_row.iloc[0]['Future Stock Short'])
            
            idx_total = idx_long + idx_short
            stk_total = stk_long + stk_short
            
            idx_ratio = (idx_long / idx_total) * 100 if idx_total > 0 else 0.0
            stk_ratio = (stk_long / stk_total) * 100 if stk_total > 0 else 0.0
            
            return {
                "date_formatted": date_formatted,
                "date_key": date_key,
                "index_long": idx_long,
                "index_short": idx_short,
                "index_ratio": idx_ratio,
                "stock_long": stk_long,
                "stock_short": stk_short,
                "stock_ratio": stk_ratio
            }
    except Exception as e:
        pass
    return None

def fetch_fii_trend_data():
    """Fetches FII trend data for the last 5 trading days using caching, including Nifty 50 close/change."""
    # 1. Load cache
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except Exception:
            cache = {}
            
    # 2. Fetch missing dates going back day-by-day
    successful_days = []
    
    # We will search up to 15 calendar days back to ensure we get 5 successful trading days
    for i in range(15):
        date_to_check = datetime.datetime.now() - datetime.timedelta(days=i)
        # Format as DDMMYYYY for URL and YYYY-MM-DD for key
        date_str = date_to_check.strftime("%d%m%Y")
        date_formatted = date_to_check.strftime("%d-%b-%Y")
        
        # Check cache first
        if date_str in cache:
            successful_days.append(cache[date_str])
            if len(successful_days) == 5:
                break
            continue
            
        # Download from archives.nseindia.com (No Akamai protection, easy standard requests)
        url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{date_str}.csv"
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                parsed = parse_fii_oi_csv(r.text, date_formatted, date_str)
                if parsed:
                    cache[date_str] = parsed
                    successful_days.append(parsed)
                    if len(successful_days) == 5:
                        break
        except Exception:
            pass
            
    # Save cache
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass
        
    # Sort successful days by date ascending (oldest first)
    successful_days.sort(key=lambda x: datetime.datetime.strptime(x['date_key'], "%d%m%Y"))
    
    # Fetch Nifty data for mapping close prices and percent changes
    nifty_map = {}
    try:
        nifty = yf.download("^NSEI", period="20d", progress=False)
        if not nifty.empty:
            if isinstance(nifty.columns, pd.MultiIndex):
                nifty.columns = nifty.columns.get_level_values(0)
            nifty['pct_change'] = nifty['Close'].pct_change() * 100
            for dt, row in nifty.iterrows():
                # Format dt to %d%m%Y to match date_str key (e.g. 24062026)
                d_key = dt.strftime("%d%m%Y")
                close_val = float(row['Close'])
                change_val = float(row['pct_change'])
                nifty_map[d_key] = {
                    "nifty_close": close_val,
                    "nifty_change": change_val if not pd.isna(change_val) else 0.0
                }
    except Exception as e:
        pass
        
    # Calculate Net positions, Day-over-Day Changes, and map Nifty performance
    for idx in range(len(successful_days)):
        day = successful_days[idx]
        
        # Calculate Index Net and Stock Net
        day['index_net'] = day['index_long'] - day['index_short']
        day['stock_net'] = day['stock_long'] - day['stock_short']
        
        # Calculate Net Change compared to previous day
        if idx == 0:
            day['index_net_change'] = 0
            day['stock_net_change'] = 0
        else:
            prev_day = successful_days[idx - 1]
            day['index_net_change'] = day['index_net'] - prev_day['index_net']
            day['stock_net_change'] = day['stock_net'] - prev_day['stock_net']
            
        # Map Nifty close & change
        d_key = day['date_key']
        if d_key in nifty_map:
            day['nifty_close'] = nifty_map[d_key]['nifty_close']
            day['nifty_change'] = nifty_map[d_key]['nifty_change']
        else:
            day['nifty_close'] = None
            day['nifty_change'] = None
            
    return successful_days

def run_scan():
    """Runs the scan and returns a structured dictionary of data."""
    # Fetch Sector and F&O data
    session = init_nse_session()
    if not session:
        return {"error": "Could not connect to NSE"}
        
    sectors_df = fetch_top_sector(session)
    if sectors_df is None or sectors_df.empty:
        return {"error": "Sector data not found"}
        
    top_sector_row = sectors_df.iloc[0]
    top_sector = top_sector_row['index']
    top_sector_change = top_sector_row['change']
    top_sector_breadth = top_sector_row['breadth']
    
    sector_constituents = SECTOR_MAP[top_sector]
    
    oi_df = fetch_nse_oi_spurts(session)
    if oi_df is None or oi_df.empty:
        return {"error": "OI data not found"}
        
    active_df = oi_df.sort_values(by='fut_value', ascending=False).head(10)
    active_symbols = active_df['symbol'].tolist()
    
    # Combine all symbols and filter out indices before querying yfinance
    all_symbols = list(set(sector_constituents + active_symbols))
    index_symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']
    all_symbols = [sym for sym in all_symbols if sym not in index_symbols]
    
    price_map = fetch_yfinance_prices(all_symbols)
    
    # Process Sectoral Stocks
    sector_stocks = []
    for symbol in sector_constituents:
        symbol_oi_row = oi_df[oi_df['symbol'] == symbol]
        if symbol_oi_row.empty:
            oi_change = 0.0
            volume = 0
            fut_value = 0.0
            ltp = None
        else:
            oi_change = symbol_oi_row.iloc[0]['oi_change']
            volume = symbol_oi_row.iloc[0]['volume']
            fut_value = symbol_oi_row.iloc[0]['fut_value']
            ltp = symbol_oi_row.iloc[0]['ltp_nse']
            
        y_data = price_map.get(symbol, {'price': None, 'change': None})
        price = y_data['price'] if y_data['price'] else ltp
        price_change = y_data['change']
        
        buildup = "Neutral"
        if price_change is not None and oi_change is not None:
            if price_change > 0.1 and oi_change > 1.0:
                buildup = "Long Buildup"
            elif price_change < -0.1 and oi_change > 1.0:
                buildup = "Short Buildup"
            elif price_change > 0.1 and oi_change < -1.0:
                buildup = "Short Covering"
            elif price_change < -0.1 and oi_change < -1.0:
                buildup = "Long Unwinding"
                
        sector_stocks.append({
            'symbol': symbol,
            'price': price,
            'price_change': price_change,
            'oi_change': oi_change,
            'volume': volume,
            'value_crores': fut_value,
            'buildup': buildup
        })
        
    sec_df = pd.DataFrame(sector_stocks)
    sec_df['buildup_rank'] = sec_df['buildup'].map({
        'Long Buildup': 1,
        'Short Covering': 2,
        'Neutral': 3,
        'Long Unwinding': 4,
        'Short Buildup': 5
    })
    sec_df = sec_df.sort_values(by=['buildup_rank', 'oi_change', 'price_change'], ascending=[True, False, False])
    
    # Process Global Most Active Futures
    active_stocks = []
    for symbol in active_symbols:
        # Skip index contracts from display table if they occur in active list
        if symbol in index_symbols:
            continue
            
        symbol_oi_row = oi_df[oi_df['symbol'] == symbol]
        oi_change = symbol_oi_row.iloc[0]['oi_change']
        volume = symbol_oi_row.iloc[0]['volume']
        fut_value = symbol_oi_row.iloc[0]['fut_value']
        ltp = symbol_oi_row.iloc[0]['ltp_nse']
        
        y_data = price_map.get(symbol, {'price': None, 'change': None})
        price = y_data['price'] if y_data['price'] else ltp
        price_change = y_data['change']
        
        buildup = "Neutral"
        if price_change is not None and oi_change is not None:
            if price_change > 0.1 and oi_change > 1.0:
                buildup = "Long Buildup"
            elif price_change < -0.1 and oi_change > 1.0:
                buildup = "Short Buildup"
            elif price_change > 0.1 and oi_change < -1.0:
                buildup = "Short Covering"
            elif price_change < -0.1 and oi_change < -1.0:
                buildup = "Long Unwinding"
                
        active_stocks.append({
            'symbol': symbol,
            'price': price,
            'price_change': price_change,
            'oi_change': oi_change,
            'volume': volume,
            'value_crores': fut_value,
            'buildup': buildup
        })
        
    act_df = pd.DataFrame(active_stocks).sort_values(by='value_crores', ascending=False)
    
    # Calculate recommendations
    recommendations = []
    long_buildup_sector = sec_df[sec_df['buildup'] == 'Long Buildup']
    long_buildup_active = act_df[act_df['buildup'] == 'Long Buildup']
    
    if len(long_buildup_sector) >= 1:
        recommendations.append(long_buildup_sector.iloc[0].to_dict())
    if len(long_buildup_active) >= 1:
        rec1_sym = recommendations[0]['symbol'] if recommendations else ""
        active_rec = long_buildup_active[long_buildup_active['symbol'] != rec1_sym]
        if not active_rec.empty:
            recommendations.append(active_rec.iloc[0].to_dict())
            
    if len(recommendations) < 2:
        for stock in long_buildup_sector.to_dict(orient='records'):
            if stock['symbol'] not in [r['symbol'] for r in recommendations]:
                recommendations.append(stock)
                if len(recommendations) == 2: break
                
    if len(recommendations) < 2:
        for stock in long_buildup_active.to_dict(orient='records'):
            if stock['symbol'] not in [r['symbol'] for r in recommendations]:
                recommendations.append(stock)
                if len(recommendations) == 2: break
                
    if len(recommendations) < 2 and not sec_df.empty:
        for stock in sec_df.to_dict(orient='records'):
            if stock['symbol'] not in [r['symbol'] for r in recommendations]:
                recommendations.append(stock)
                if len(recommendations) == 2: break

    # Clean nan values for JSON compliance
    def clean_records(records):
        clean_list = []
        for r in records:
            clean_rec = {}
            for k, v in r.items():
                if pd.isna(v) or v is None:
                    clean_rec[k] = None
                else:
                    clean_rec[k] = v
            clean_list.append(clean_rec)
        return clean_list
        
    # Fetch FII Open Interest Trend (Last 5 trading days)
    fii_trend = fetch_fii_trend_data()
        
    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "top_sector": top_sector,
        "sector_change": float(top_sector_change),
        "sector_breadth": float(top_sector_breadth),
        "advances": int(top_sector_row['advances']),
        "declines": int(top_sector_row['declines']),
        "sectors": clean_records(sectors_df.to_dict(orient='records')),
        "stocks": clean_records(sec_df.to_dict(orient='records')),
        "active_futures": clean_records(act_df.to_dict(orient='records')),
        "recommendations": clean_records(recommendations),
        "fii_trend": fii_trend
    }

def print_cli_results(result):
    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        return
        
    console.print(Panel("[bold green]NSE Sector & Stock Futures OI Buildup Scanner[/bold green]", subtitle="FII & Pro Money Flow Tracker"))
    
    # FII Open Interest Trend Table
    table_fii = Table(title="🏛️ FII Participant Open Interest Trend (Last 5 Days)")
    table_fii.add_column("Date", style="bold")
    table_fii.add_column("Nifty 50", justify="right")
    table_fii.add_column("Index Long", justify="right")
    table_fii.add_column("Index Short", justify="right")
    table_fii.add_column("Index Net (Chg)", justify="right", style="bold")
    table_fii.add_column("Index L/S %", justify="center", style="bold")
    table_fii.add_column("Stock Long", justify="right")
    table_fii.add_column("Stock Short", justify="right")
    table_fii.add_column("Stock Net (Chg)", justify="right", style="bold")
    table_fii.add_column("Stock L/S %", justify="center", style="bold")
    
    for row in result['fii_trend']:
        idx_color = "green" if row['index_ratio'] >= 60 else "yellow" if row['index_ratio'] >= 45 else "red"
        stk_color = "green" if row['stock_ratio'] >= 60 else "yellow" if row['stock_ratio'] >= 45 else "red"
        
        # Nifty formatting
        nifty_str = "N/A"
        if row.get('nifty_close'):
            nifty_str = f"{row['nifty_close']:,.2f} ({row['nifty_change']:+.2f}%)"
            
        # Net change formatting
        idx_net_val = row['index_net']
        idx_net_chg = row['index_net_change']
        idx_net_str = f"{idx_net_val:+,} ({idx_net_chg:+,})"
        idx_net_color = "green" if idx_net_chg > 0 else "red" if idx_net_chg < 0 else "white"
        
        stk_net_val = row['stock_net']
        stk_net_chg = row['stock_net_change']
        stk_net_str = f"{stk_net_val:+,} ({stk_net_chg:+,})"
        stk_net_color = "green" if stk_net_chg > 0 else "red" if stk_net_chg < 0 else "white"
        
        table_fii.add_row(
            row['date_formatted'],
            nifty_str,
            f"{row['index_long']:,}",
            f"{row['index_short']:,}",
            f"[{idx_net_color}]{idx_net_str}[/{idx_net_color}]",
            f"[{idx_color}]{row['index_ratio']:.1f}%[/{idx_color}]",
            f"{row['stock_long']:,}",
            f"{row['stock_short']:,}",
            f"[{stk_net_color}]{stk_net_str}[/{stk_net_color}]",
            f"[{stk_color}]{row['stock_ratio']:.1f}%[/{stk_color}]"
        )
    console.print(table_fii)
    
    # Recommendations
    console.print("\n[bold gold3]================================================================[/bold gold3]")
    console.print("[bold gold3]           DIRECTIONAL TRADE RECOMMENDATION (TOP 2 STOCKS)      [/bold gold3]")
    console.print("[bold gold3]================================================================[/bold gold3]")
    for idx, rec in enumerate(result['recommendations'], 1):
        rec_type = "STRONG BULLISH LONG" if rec['buildup'] == "Long Buildup" else "STRONG BEARISH SHORT" if rec['buildup'] == "Short Buildup" else f"MILD - {rec['buildup']}"
        rec_color = "bold green" if "LONG" in rec_type else "bold red" if "SHORT" in rec_type else "bold yellow"
        console.print(f"[{rec_color}]🚀 Recommendation {idx} ({rec_type}): {rec['symbol']}[/{rec_color}]")
        price_str = f"Rs. {rec['price']:,.2f}" if rec['price'] else "N/A"
        p_chg_str = f"{rec['price_change']:+.2f}%" if rec['price_change'] else "N/A"
        oi_chg_str = f"{rec['oi_change']:+.2f}%" if rec['oi_change'] else "N/A"
        val_str = f"{rec['value_crores']:.1f} Cr" if rec['value_crores'] else "0.0 Cr"
        console.print(f"   LTP: {price_str} | Price Change: {p_chg_str} | OI Change: {oi_chg_str} | Traded Value: {val_str}")

if __name__ == "__main__":
    result = run_scan()
    print_cli_results(result)
