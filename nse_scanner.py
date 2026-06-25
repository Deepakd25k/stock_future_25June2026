import os
import sys
import json
import time
import requests
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Initialize Rich Console for beautiful terminal formatting
console = Console()

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
        time.sleep(2)
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

def run_scan():
    """Runs the scan and returns a structured dictionary of data."""
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
    
    constituents = SECTOR_MAP[top_sector]
    
    oi_df = fetch_nse_oi_spurts(session)
    if oi_df is None or oi_df.empty:
        return {"error": "OI data not found"}
        
    price_map = fetch_yfinance_prices(constituents)
    
    consolidated_data = []
    for symbol in constituents:
        symbol_oi_row = oi_df[oi_df['symbol'] == symbol]
        if symbol_oi_row.empty:
            oi_change = 0.0
            volume = 0
            ltp = None
        else:
            oi_change = symbol_oi_row.iloc[0]['oi_change']
            volume = symbol_oi_row.iloc[0]['volume']
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
                
        consolidated_data.append({
            'symbol': symbol,
            'price': price,
            'price_change': price_change,
            'oi_change': oi_change,
            'volume': volume,
            'buildup': buildup
        })
        
    res_df = pd.DataFrame(consolidated_data)
    res_df['buildup_rank'] = res_df['buildup'].map({
        'Long Buildup': 1,
        'Short Covering': 2,
        'Neutral': 3,
        'Long Unwinding': 4,
        'Short Buildup': 5
    })
    res_df = res_df.sort_values(by=['buildup_rank', 'oi_change', 'price_change'], ascending=[True, False, False])
    
    # Calculate recommendations
    recommendations = []
    long_buildup_stocks = res_df[res_df['buildup'] == 'Long Buildup']
    if len(long_buildup_stocks) >= 2:
        recommendations.append(long_buildup_stocks.iloc[0].to_dict())
        recommendations.append(long_buildup_stocks.iloc[1].to_dict())
    elif len(long_buildup_stocks) == 1:
        recommendations.append(long_buildup_stocks.iloc[0].to_dict())
        other_stocks = res_df[res_df['symbol'] != long_buildup_stocks.iloc[0]['symbol']]
        if not other_stocks.empty:
            recommendations.append(other_stocks.iloc[0].to_dict())
    else:
        short_buildup_stocks = res_df[res_df['buildup'] == 'Short Buildup']
        if len(short_buildup_stocks) >= 2:
            recommendations.append(short_buildup_stocks.iloc[0].to_dict())
            recommendations.append(short_buildup_stocks.iloc[1].to_dict())
        elif not res_df.empty:
            recommendations.append(res_df.iloc[0].to_dict())
            if len(res_df) > 1:
                recommendations.append(res_df.iloc[1].to_dict())
                
    # Parse nan values for JSON compliance
    clean_stocks = []
    for s in res_df.to_dict(orient='records'):
        clean_stock = {}
        for k, v in s.items():
            if pd.isna(v) or v is None:
                clean_stock[k] = None
            else:
                clean_stock[k] = v
        clean_stocks.append(clean_stock)

    clean_recs = []
    for r in recommendations:
        clean_rec = {}
        for k, v in r.items():
            if pd.isna(v) or v is None:
                clean_rec[k] = None
            else:
                clean_rec[k] = v
        clean_recs.append(clean_rec)
        
    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "top_sector": top_sector,
        "sector_change": float(top_sector_change),
        "sector_breadth": float(top_sector_breadth),
        "advances": int(top_sector_row['advances']),
        "declines": int(top_sector_row['declines']),
        "sectors": sectors_df.to_dict(orient='records'),
        "stocks": clean_stocks,
        "recommendations": clean_recs
    }

def print_cli_results(result):
    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        return
        
    console.print(Panel("[bold green]NSE Sector & Stock Futures OI Buildup Scanner[/bold green]", subtitle="FII & Pro Money Flow Tracker"))
    
    # Sector Table
    table_sec = Table(title="Sectoral Rankings (Ranked by % Change)")
    table_sec.add_column("Rank", justify="center", style="dim")
    table_sec.add_column("Sector Name", style="bold")
    table_sec.add_column("Change %", justify="right")
    table_sec.add_column("Advances - Declines", justify="center")
    table_sec.add_column("Breadth (Green %)", justify="right")
    
    for idx, row in enumerate(result['sectors'], 1):
        color = "green" if row['change'] > 0 else "red"
        breadth_color = "green" if row['breadth'] >= 70 else "yellow" if row['breadth'] >= 50 else "red"
        
        table_sec.add_row(
            str(idx),
            row['index'],
            f"[{color}]{row['change']:+.2f}%[/{color}]",
            f"{row['advances']} - {row['declines']}",
            f"[{breadth_color}]{row['breadth']:.1f}%[/{breadth_color}]"
        )
    console.print(table_sec)
    
    # Selection Details
    console.print(f"\n[bold gold3]Selected Sector: {result['top_sector']} ({result['sector_change']:+.2f}%, Breadth: {result['sector_breadth']:.1f}%)[/bold gold3]")
    if result['sector_breadth'] < 70.0:
        console.print("[bold yellow]⚠️ WARNING: Sector breadth is under 70%! The index rise is driven by a few heavyweights. Proceed with caution.[/bold yellow]")
    else:
        console.print("[bold green]✅ Sector breadth is STRONG (>70% stocks green). Money is flowing broadly across the sector.[/bold green]")
        
    # Stock Table
    table_stocks = Table(title=f"Stocks Analysis in {result['top_sector']}")
    table_stocks.add_column("Symbol", style="bold")
    table_stocks.add_column("LTP (Rs.)", justify="right")
    table_stocks.add_column("Price Change %", justify="right")
    table_stocks.add_column("OI Change %", justify="right")
    table_stocks.add_column("Volume (Contracts)", justify="right", style="dim")
    table_stocks.add_column("Buildup Category", justify="center")
    
    for row in result['stocks']:
        price_change = row['price_change']
        p_chg_str = f"{price_change:+.2f}%" if price_change is not None else "N/A"
        p_chg_color = "green" if (price_change and price_change > 0) else "red" if (price_change and price_change < 0) else "white"
        
        oi_change = row['oi_change']
        oi_chg_str = f"{oi_change:+.2f}%" if oi_change is not None else "N/A"
        oi_chg_color = "green" if (oi_change and oi_change > 0) else "red" if (oi_change and oi_change < 0) else "white"
        
        price = row['price']
        price_str = f"{price:,.2f}" if price is not None else "N/A"
        
        buildup = row['buildup']
        b_style = "bold green" if buildup == "Long Buildup" else "bold red" if buildup == "Short Buildup" else "green" if buildup == "Short Covering" else "red" if buildup == "Long Unwinding" else "white"
        
        table_stocks.add_row(
            row['symbol'],
            price_str,
            f"[{p_chg_color}]{p_chg_str}[/{p_chg_color}]",
            f"[{oi_chg_color}]{oi_chg_str}[/{oi_chg_color}]",
            f"{row['volume']:,}",
            f"[{b_style}]{buildup}[/{b_style}]"
        )
    console.print(table_stocks)
    
    # Recommendations
    console.print("\n[bold gold3]================================================================[/bold gold3]")
    console.print("[bold gold3]           DIRECTIONAL TRADE RECOMMENDATION (TOP 2 STOCKS)      [/bold gold3]")
    console.print("[bold gold3]================================================================[/bold gold3]")
    
    for idx, rec in enumerate(result['recommendations'], 1):
        rec_type = "STRONG BULLISH LONG" if rec['buildup'] == "Long Buildup" else "STRONG BEARISH SHORT" if rec['buildup'] == "Short Buildup" else f"MILD BULLISH - {rec['buildup']}"
        rec_color = "bold green" if "LONG" in rec_type else "bold red" if "SHORT" in rec_type else "bold yellow"
        
        console.print(f"[{rec_color}]🚀 Recommendation {idx} ({rec_type}): {rec['symbol']}[/{rec_color}]")
        price_str = f"Rs. {rec['price']:,.2f}" if rec['price'] else "N/A"
        p_chg_str = f"{rec['price_change']:+.2f}%" if rec['price_change'] else "N/A"
        oi_chg_str = f"{rec['oi_change']:+.2f}%" if rec['oi_change'] else "N/A"
        console.print(f"   LTP: {price_str} | Price Change: {p_chg_str} | OI Change: {oi_chg_str}")

if __name__ == "__main__":
    result = run_scan()
    print_cli_results(result)
