import logging
from datetime import datetime
import astrology
from groww_client import GrowwClient

logger = logging.getLogger("strategy")
logging.basicConfig(level=logging.INFO)

# Sector and Stock mapping
SECTORS = {
    "NIFTY IT": ["TCS", "INFY", "WIPRO", "HCLTECH"],
    "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"],
    "NIFTY METAL": ["TATASTEEL", "JINDALSTEL", "HINDALCO"],
    "NIFTY AUTO": ["TMPV", "TMCV", "MARUTI", "M&M"],
    "NIFTY PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY"]
}

# Index symbols to fetch quotes for
SECTOR_INDEX_SYMBOLS = {
    "NIFTY IT": "NIFTYIT",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY METAL": "NIFTYMETAL",
    "NIFTY AUTO": "NIFTYAUTO",
    "NIFTY PHARMA": "NIFTYPHARMA"
}

def is_market_hours(dt: datetime) -> bool:
    """Checks if the given datetime is within NSE market hours (09:15 AM - 03:30 PM, Mon-Fri)."""
    dt_kol = dt.astimezone(astrology.KOLKATA_TZ)
    if dt_kol.weekday() >= 5:  # Saturday or Sunday
        return False
    
    from datetime import time as datetime_time
    market_start = datetime_time(9, 15)
    market_end = datetime_time(15, 30)
    current_time = dt_kol.time()
    
    return market_start <= current_time <= market_end

class StrategyEngine:
    def __init__(self, groww_client: GrowwClient):
        self.groww = groww_client

    def get_market_status(self) -> dict:
        """Determines the market trend, VIX, and identifies the weakest sector."""
        # 1. Fetch Nifty 50 to see trend
        nifty_quote = self.groww.get_quote("NIFTY")
        nifty_change = nifty_quote.get("day_change_perc", 0.0)
        trend = "Bearish" if nifty_change < 0 else "Bullish"
        
        # 2. Fetch India VIX
        vix_quote = self.groww.get_quote("INDIAVIX")
        vix_val = vix_quote.get("last_price", 15.0)
        
        # 3. Find the weakest sector by fetching sector index quotes
        weakest_sector = None
        min_change = 999.0
        
        sector_details = {}
        for sector, symbol in SECTOR_INDEX_SYMBOLS.items():
            try:
                quote = self.groww.get_quote(symbol)
                change = quote.get("day_change_perc", 0.0)
                sector_details[sector] = change
                if change < min_change:
                    min_change = change
                    weakest_sector = sector
            except Exception as e:
                logger.error(f"Failed to fetch index quote for {sector} ({symbol}): {e}")
                
        # Fallback if sector quotes fail
        if not weakest_sector:
            weakest_sector = "NIFTY IT"
            min_change = -1.5
            sector_details = {s: 0.0 for s in SECTORS.keys()}
            sector_details[weakest_sector] = min_change

        return {
            "trend": trend,
            "nifty_change": nifty_change,
            "vix": vix_val,
            "weakest_sector": weakest_sector,
            "weakest_sector_change": min_change,
            "sector_details": sector_details
        }

    def select_weakest_stock(self, weakest_sector: str) -> dict:
        """Finds the weakest stock in the weakest sector that is below its VWAP."""
        stocks = SECTORS.get(weakest_sector, [])
        selected_stock = None
        min_change = 999.0
        ltp_final = 0.0
        vwap_final = 0.0
        short_reason = ""
        below_vwap_confirmed = False

        for stock in stocks:
            try:
                quote = self.groww.get_quote(stock)
                change = quote.get("day_change_perc", 0.0)
                
                # Fetch LTP and VWAP
                ltp, vwap = self.groww.get_ltp_and_vwap(stock)
                
                if ltp < vwap:  # Below VWAP check
                    if change < min_change:
                        min_change = change
                        selected_stock = stock
                        ltp_final = ltp
                        vwap_final = vwap
                        below_vwap_confirmed = True
                        short_reason = f"Weakest stock in {weakest_sector} (Change: {change:.2f}%) trading below VWAP."
            except Exception as e:
                logger.error(f"Failed to analyze stock {stock}: {e}")

        # Fallback if no stock is below VWAP, or API fails
        if not selected_stock and stocks:
            # Fallback to the first stock in the sector for testing
            selected_stock = stocks[0]
            ltp_final, vwap_final = self.groww.get_ltp_and_vwap(selected_stock)
            min_change = -1.0
            below_vwap_confirmed = ltp_final < vwap_final
            short_reason = f"Fallback stock in {weakest_sector}."

        return {
            "symbol": selected_stock,
            "change": min_change,
            "ltp": ltp_final,
            "vwap": vwap_final,
            "below_vwap_confirmed": below_vwap_confirmed,
            "short_reason": short_reason
        }

    def generate_trade_plan(self, stock_info: dict) -> dict:
        """Calculates Entry, SL, and Target levels based on 2:1 reward/risk ratio."""
        ltp = stock_info["ltp"]
        vwap = stock_info["vwap"]
        
        # Stop Loss: 1% above Entry or just above VWAP (whichever is higher)
        # Added safety gap of 0.2%
        sl = max(vwap * 1.002, ltp * 1.01)
        risk = sl - ltp
        
        # Target T1: 1:1 risk-to-reward ratio
        t1 = ltp - risk
        # Target T2: 2:1 risk-to-reward ratio (final target)
        t2 = ltp - (2 * risk)
        
        return {
            "entry": ltp,
            "sl": sl,
            "t1": t1,
            "t2": t2,
            "risk": risk
        }

    def evaluate_strategy(self) -> dict:
        """Runs the entire strategy pipeline and returns the final verdict."""
        now = datetime.now()
        
        # 1. Astrological checks
        permission = astrology.get_personal_permission_status(now)
        rk_check = astrology.check_trading_window_details(now)
        
        # 2. Market Status checks
        market = self.get_market_status()
        
        # 3. Stock Selection and VWAP
        stock = self.select_weakest_stock(market["weakest_sector"])
        
        # 4. Trade Plan
        plan = self.generate_trade_plan(stock)
        
        # 5. Final Verdict Logic
        verdict = "AVOID"
        avoid_reasons = []
        
        market_open = is_market_hours(now)
        
        if not permission["allowed"]:
            avoid_reasons.append("Personal Permission DENIED: Current Moon transit lords do not favor wealth/career houses (6, 10, 11).")
        if rk_check["is_in_rahu_kaal"]:
            avoid_reasons.append("Rahu Kaal Alert: Kolkata Rahu Kaal is active. Trading prohibited.")
        if not stock["below_vwap_confirmed"]:
            avoid_reasons.append(f"VWAP Check Failed: Stock {stock['symbol']} is trading above its VWAP.")
        if not market_open:
            avoid_reasons.append("Market Closed: Trading is only allowed during NSE market hours (09:15 AM - 03:30 PM, Mon-Fri).")
        if market["trend"] != "Bearish":
            # We still allow it, but flag as warning
            logger.warning("Market trend is Bullish, but strategy will execute if other conditions are met.")
            
        # Check overall verdict
        if permission["allowed"] and not rk_check["is_in_rahu_kaal"] and stock["below_vwap_confirmed"] and stock["symbol"] and market_open:
            verdict = "EXECUTE SHORT"
            
        # Probability calculation
        # Base probability = KP Score (max 100).
        # We adjust it based on technical factors:
        # +10% if VIX is high (>18)
        # +10% if market trend is Bearish
        probability = permission["score"]
        if market["vix"] > 18.0:
            probability = min(100, probability + 10)
        if market["trend"] == "Bearish":
            probability = min(100, probability + 10)
            
        return {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "personal_permission": {
                "status": "ALLOWED" if permission["allowed"] else "DENIED",
                "reason": f"KP Score: {permission['score']}%. Lords: Sign({permission['kp_details']['sign_lord']}), Star({permission['kp_details']['star_lord']}), Sub({permission['kp_details']['sub_lord']})",
                "score": permission["score"]
            },
            "market_status": {
                "trend": market["trend"],
                "vix": market["vix"],
                "weakest_sector": market["weakest_sector"],
                "weakest_sector_change": market["weakest_sector_change"]
            },
            "selected_stock": {
                "symbol": stock["symbol"],
                "short_reason": stock["short_reason"],
                "below_vwap_confirmed": "YES" if stock["below_vwap_confirmed"] else "NO"
            },
            "kp_score": permission["score"],
            "probability": f"{probability}%",
            "trade_plan": plan,
            "time_window": {
                "window": f"Avoid {rk_check['rahu_kaal_start']} - {rk_check['rahu_kaal_end']} (Kolkata Rahu Kaal)",
                "status": "INACTIVE" if not rk_check["is_in_rahu_kaal"] else "ACTIVE"
            },
            "verdict": verdict,
            "avoid_reasons": avoid_reasons
        }
