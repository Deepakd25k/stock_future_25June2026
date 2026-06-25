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
        # Request homepage to set cookies
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(2)
        # Request equity derivatives watch page to get deeper cookies
        s.get("https://www.nseindia.com/market-data/equity-derivatives-watch", timeout=10)
        time.sleep(1)
        return s
    except Exception as e:
        console.print(f"[red]Error initializing NSE session: {e}[/red]")
        return None

def fetch_top_sector(session):
    """Fetches all indices and ranks them to find the top outperforming sector."""
    url = "https://www.nseindia.com/api/allIndices"
    referer = "https://www.nseindia.com/market-data/live-market-indices"
    try:
        r = session.get(url, headers={"Referer": referer}, timeout=10)
        if r.status_code != 200:
            console.print(f"[red]Failed to fetch indices from NSE. HTTP status: {r.status_code}[/red]")
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
        
        # Sort by percentage change descending
        sector_df = pd.DataFrame(sector_data).sort_values(by='change', ascending=False)
        return sector_df
    except Exception as e:
        console.print(f"[red]Error parsing sectoral indices: {e}[/red]")
        return None

def fetch_nse_oi_spurts(session):
    """Fetches F&O Open Interest data for all underlyings."""
    url = "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings"
    referer = "https://www.nseindia.com/market-data/equity-derivatives-watch"
    try:
        r = session.get(url, headers={"Referer": referer}, timeout=10)
        if r.status_code != 200:
            console.print(f"[red]Failed to fetch F&O Open Interest from NSE. HTTP status: {r.status_code}[/red]")
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
        console.print(f"[red]Error parsing OI spurts: {e}[/red]")
        return None

def fetch_yfinance_prices(symbols):
    """Fetches live stock price changes from Yahoo Finance using yfinance download."""
    # Map NSE symbol to Yahoo Finance symbol by appending .NS
    yf_symbols = [f"{sym}.NS" for sym in symbols]
    try:
        # Download last 5 days to ensure we have at least 2 trading days to calculate daily change
        data = yf.download(" ".join(yf_symbols), period="5d", progress=False)
        if data.empty or 'Close' not in data:
            return {}
        
        close_data = data['Close']
        # If single ticker downloaded, close_data is a Series, make it a DataFrame
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
                
                # Handle delisted or missing quotes (like Tata Motors temporarily)
                if pd.isna(last_price) or pd.isna(prev_price):
                    price_map[nse_sym] = {'price': None, 'change': None}
                else:
                    pct_change = ((last_price - prev_price) / prev_price) * 100
                    price_map[nse_sym] = {'price': last_price, 'change': pct_change}
            except KeyError:
                price_map[nse_sym] = {'price': None, 'change': None}
        return price_map
    except Exception as e:
        console.print(f"[yellow]Warning fetching Yahoo Finance prices: {e}[/yellow]")
        return {}

def scan_market():
    console.print(Panel("[bold green]NSE Sector & Stock Futures OI Buildup Scanner[/bold green]", subtitle="FII & Pro Money Flow Tracker"))
    
    # 1. Initialize NSE Session
    console.print("[cyan]Initializing NSE Session and cookies...[/cyan]")
    session = init_nse_session()
    if not session:
        console.print("[red]Aborting scan: Could not connect to NSE.[/red]")
        return
    
    # 2. Get Top Sectors
    console.print("[cyan]Scanning sectoral indices performance...[/cyan]")
    sectors_df = fetch_top_sector(session)
    if sectors_df is None or sectors_df.empty:
        console.print("[red]Aborting scan: Sectoral indices details not found.[/red]")
        return
    
    # Print Sectoral Rankings
    table_sec = Table(title="Sectoral Rankings (Ranked by % Change)")
    table_sec.add_column("Rank", justify="center", style="dim")
    table_sec.add_column("Sector Name", style="bold")
    table_sec.add_column("Change %", justify="right")
    table_sec.add_column("Advances - Declines", justify="center")
    table_sec.add_column("Breadth (Green %)", justify="right")
    
    for idx, row in enumerate(sectors_df.itertuples(), 1):
        color = "green" if row.change > 0 else "red"
        breadth_color = "green" if row.breadth >= 70 else "yellow" if row.breadth >= 50 else "red"
        
        table_sec.add_row(
            str(idx),
            row.index,
            f"[{color}]{row.change:+.2f}%[/{color}]",
            f"{row.advances} - {row.declines}",
            f"[{breadth_color}]{row.breadth:.1f}%[/{breadth_color}]"
        )
    console.print(table_sec)
    
    # Select Top Sector
    top_sector_row = sectors_df.iloc[0]
    top_sector = top_sector_row['index']
    top_sector_change = top_sector_row['change']
    top_sector_breadth = top_sector_row['breadth']
    
    console.print(f"\n[bold gold3]Selected Sector: {top_sector} ({top_sector_change:+.2f}%, Breadth: {top_sector_breadth:.1f}%)[/bold gold3]")
    
    # Warn if breadth is weak
    if top_sector_breadth < 70.0:
        console.print("[bold yellow]⚠️ WARNING: Sector breadth is under 70%! The index rise is driven by a few heavyweights. Proceed with caution.[/bold yellow]")
    else:
        console.print("[bold green]✅ Sector breadth is STRONG (>70% stocks green). Money is flowing broadly across the sector.[/bold green]")
    
    # 3. Get Sector constituents
    constituents = SECTOR_MAP[top_sector]
    console.print(f"[cyan]Constituents of {top_sector}: {', '.join(constituents)}[/cyan]")
    
    # 4. Fetch OI spurts for F&O
    console.print("[cyan]Fetching Open Interest data from NSE...[/cyan]")
    oi_df = fetch_nse_oi_spurts(session)
    if oi_df is None or oi_df.empty:
        console.print("[red]Aborting scan: Could not fetch F&O Open Interest data.[/red]")
        return
        
    # 5. Fetch Stock prices from Yahoo Finance
    console.print("[cyan]Fetching stock prices from Yahoo Finance...[/cyan]")
    price_map = fetch_yfinance_prices(constituents)
    
    # 6. Correlate and calculate buildup
    consolidated_data = []
    for symbol in constituents:
        # Match OI
        symbol_oi_row = oi_df[oi_df['symbol'] == symbol]
        if symbol_oi_row.empty:
            # If F&O stock doesn't show in today's OI spurts list, assume 0.0% OI change
            oi_change = 0.0
            volume = 0
            ltp = None
        else:
            oi_change = symbol_oi_row.iloc[0]['oi_change']
            volume = symbol_oi_row.iloc[0]['volume']
            ltp = symbol_oi_row.iloc[0]['ltp_nse']
            
        # Match Price from Yahoo
        y_data = price_map.get(symbol, {'price': None, 'change': None})
        price = y_data['price'] if y_data['price'] else ltp
        price_change = y_data['change']
        
        # Calculate Buildup Category
        buildup = "Neutral"
        buildup_style = "white"
        
        if price_change is not None and oi_change is not None:
            if price_change > 0.1 and oi_change > 1.0:
                buildup = "Long Buildup"
                buildup_style = "bold green"
            elif price_change < -0.1 and oi_change > 1.0:
                buildup = "Short Buildup"
                buildup_style = "bold red"
            elif price_change > 0.1 and oi_change < -1.0:
                buildup = "Short Covering"
                buildup_style = "green"
            elif price_change < -0.1 and oi_change < -1.0:
                buildup = "Long Unwinding"
                buildup_style = "red"
                
        consolidated_data.append({
            'symbol': symbol,
            'price': price,
            'price_change': price_change,
            'oi_change': oi_change,
            'volume': volume,
            'buildup': buildup,
            'buildup_style': buildup_style
        })
        
    res_df = pd.DataFrame(consolidated_data)
    
    # Print Stock Table
    table_stocks = Table(title=f"Stocks Analysis in {top_sector}")
    table_stocks.add_column("Symbol", style="bold")
    table_stocks.add_column("LTP (Rs.)", justify="right")
    table_stocks.add_column("Price Change %", justify="right")
    table_stocks.add_column("OI Change %", justify="right")
    table_stocks.add_column("Volume (Contracts)", justify="right", style="dim")
    table_stocks.add_column("Buildup Category", justify="center")
    
    # Sort stocks by Buildup and OI Change
    # Priority: 1. Long Buildup, 2. Short Covering, 3. Neutral/Others (for long trades)
    res_df['buildup_rank'] = res_df['buildup'].map({
        'Long Buildup': 1,
        'Short Covering': 2,
        'Neutral': 3,
        'Long Unwinding': 4,
        'Short Buildup': 5
    })
    # Sort: prioritising Long Buildup, then highest OI Change, then highest Price Change
    res_df = res_df.sort_values(by=['buildup_rank', 'oi_change', 'price_change'], ascending=[True, False, False])
    
    for row in res_df.itertuples():
        p_chg_str = f"{row.price_change:+.2f}%" if row.price_change is not None else "N/A"
        p_chg_color = "green" if (row.price_change and row.price_change > 0) else "red" if (row.price_change and row.price_change < 0) else "white"
        
        oi_chg_str = f"{row.oi_change:+.2f}%" if row.oi_change is not None else "N/A"
        oi_chg_color = "green" if (row.oi_change and row.oi_change > 0) else "red" if (row.oi_change and row.oi_change < 0) else "white"
        
        price_str = f"{row.price:,.2f}" if row.price is not None else "N/A"
        
        table_stocks.add_row(
            row.symbol,
            price_str,
            f"[{p_chg_color}]{p_chg_str}[/{p_chg_color}]",
            f"[{oi_chg_color}]{oi_chg_str}[/{oi_chg_color}]",
            f"{row.volume:,}",
            f"[{row.buildup_style}]{row.buildup}[/{row.buildup_style}]"
        )
    console.print(table_stocks)
    
    # 7. Recommendations
    console.print("\n[bold gold3]================================================================[/bold gold3]")
    console.print("[bold gold3]           DIRECTIONAL TRADE RECOMMENDATION (TOP 2 STOCKS)      [/bold gold3]")
    console.print("[bold gold3]================================================================[/bold gold3]")
    
    # Filter for Long Buildup stocks
    long_buildup_stocks = res_df[res_df['buildup'] == 'Long Buildup']
    
    if len(long_buildup_stocks) >= 2:
        stock1 = long_buildup_stocks.iloc[0]
        stock2 = long_buildup_stocks.iloc[1]
        console.print(f"[bold green]🚀 Recommendation 1 (STRONG BULLISH LONG): {stock1.symbol}[/bold green]")
        console.print(f"   LTP: Rs. {stock1.price:,.2f} | Price Change: {stock1.price_change:+.2f}% | OI Buildup: {stock1.oi_change:+.2f}% (FII/Pro Buying)")
        console.print(f"[bold green]🚀 Recommendation 2 (STRONG BULLISH LONG): {stock2.symbol}[/bold green]")
        console.print(f"   LTP: Rs. {stock2.price:,.2f} | Price Change: {stock2.price_change:+.2f}% | OI Buildup: {stock2.oi_change:+.2f}% (FII/Pro Buying)")
    elif len(long_buildup_stocks) == 1:
        stock1 = long_buildup_stocks.iloc[0]
        console.print(f"[bold green]🚀 Recommendation 1 (STRONG BULLISH LONG): {stock1.symbol}[/bold green]")
        console.print(f"   LTP: Rs. {stock1.price:,.2f} | Price Change: {stock1.price_change:+.2f}% | OI Buildup: {stock1.oi_change:+.2f}%")
        
        # Fallback to Short Covering or highest OI change
        other_stocks = res_df[res_df['symbol'] != stock1.symbol]
        if not other_stocks.empty:
            stock2 = other_stocks.iloc[0]
            console.print(f"[bold yellow]🚀 Recommendation 2 (MILD BULLISH - {stock2.buildup}): {stock2.symbol}[/bold yellow]")
            console.print(f"   LTP: Rs. {stock2.price:,.2f} | Price Change: {stock2.price_change:+.2f}% | OI Change: {stock2.oi_change:+.2f}%")
    else:
        # Check if we have Short Buildup (for short trade)
        short_buildup_stocks = res_df[res_df['buildup'] == 'Short Buildup']
        if len(short_buildup_stocks) >= 2:
            stock1 = short_buildup_stocks.iloc[0]
            stock2 = short_buildup_stocks.iloc[1]
            console.print(f"[bold red]📉 Recommendation 1 (STRONG BEARISH SHORT): {stock1.symbol}[/bold red]")
            console.print(f"   LTP: Rs. {stock1.price:,.2f} | Price Change: {stock1.price_change:+.2f}% | OI Buildup: {stock1.oi_change:+.2f}% (FII/Pro Selling)")
            console.print(f"[bold red]📉 Recommendation 2 (STRONG BEARISH SHORT): {stock2.symbol}[/bold red]")
            console.print(f"   LTP: Rs. {stock2.price:,.2f} | Price Change: {stock2.price_change:+.2f}% | OI Buildup: {stock2.oi_change:+.2f}% (FII/Pro Selling)")
        else:
            console.print("[bold yellow]⚠️ No clear high-conviction Long/Short Buildup stocks found in the top sector today.[/bold yellow]")
            # Recommend based on raw metrics
            top_by_oi = res_df.sort_values(by='oi_change', ascending=False)
            if not top_by_oi.empty:
                stock1 = top_by_oi.iloc[0]
                console.print(f"[cyan]💡 Alternative Ticker (Highest OI Spurt): {stock1.symbol}[/cyan]")
                console.print(f"   Price Change: {stock1.price_change:+.2f}% | OI Change: {stock1.oi_change:+.2f}% | Buildup: {stock1.buildup}")

if __name__ == "__main__":
    scan_market()
