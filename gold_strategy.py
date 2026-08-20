import logging
from datetime import datetime, time
from dataclasses import dataclass
from typing import List, Optional, Tuple
import pytz

logger = logging.getLogger("gold_strategy")
logging.basicConfig(level=logging.INFO)

IST_TZ = pytz.timezone('Asia/Kolkata')

@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    
    @property
    def is_bullish(self):
        return self.close > self.open

    @property
    def is_bearish(self):
        return self.close < self.open

@dataclass
class SessionBoundaries:
    high: float
    low: float
    is_set: bool = False

class GoldStrategyEngine:
    def __init__(self, risk_per_trade: float = 100.0, entry_style: str = "aggressive"):
        """
        :param risk_per_trade: Fixed risk per trade in base currency (e.g., INR or USD)
        :param entry_style: "aggressive" (1-candle confirmation) or "conservative" (swing confirmation)
        """
        self.risk_per_trade = risk_per_trade
        self.entry_style = entry_style
        
        self.asian_boundaries = SessionBoundaries(high=0.0, low=999999.0)
        self.last_state = "WAITING"  # WAITING, SWEEPING_HIGH, SWEEPING_LOW, BREAKOUT_HIGH, BREAKOUT_LOW
        self.trigger_candle: Optional[Candle] = None

    def _is_time_between(self, dt: datetime, start: time, end: time) -> bool:
        """Checks if a datetime is within a start and end time in IST."""
        dt_ist = dt.astimezone(IST_TZ).time()
        return start <= dt_ist <= end

    def update_15m_boundaries(self, candles_15m: List[Candle]):
        """
        Updates the Asian Session boundaries (High/Low) based on 15m candles
        from market open until 9:30 AM IST of the current day.
        """
        high = -1.0
        low = float('inf')
        
        cutoff_time = time(9, 30)
        today = datetime.now(IST_TZ).date()
        valid_candles = 0
        
        for candle in candles_15m:
            dt_ist = candle.timestamp.astimezone(IST_TZ)
            c_date = dt_ist.date()
            c_time = dt_ist.time()
            
            if c_date == today and c_time <= cutoff_time:
                valid_candles += 1
                if candle.high > high:
                    high = candle.high
                if candle.low < low:
                    low = candle.low
        
        if high != -1.0 and low != float('inf') and valid_candles > 0:
            if not self.asian_boundaries.is_set or self.asian_boundaries.high != high or self.asian_boundaries.low != low:
                self.asian_boundaries = SessionBoundaries(high=high, low=low, is_set=True)
                logger.info(f"Asian Boundaries Set/Updated: High={high}, Low={low}")
        else:
            if self.asian_boundaries.is_set:
                logger.warning("Asian boundaries invalidated (no valid candles).")
            self.asian_boundaries.is_set = False

    def is_valid_trading_window(self, dt: datetime) -> bool:
        """
        Checks if the current time is within the London or NY trading windows.
        London: 11:30 AM - 2:30 PM IST
        New York: 4:30 PM - 7:30 PM IST
        """
        # London Window
        if self._is_time_between(dt, time(11, 30), time(14, 30)):
            return True
        # NY Window
        if self._is_time_between(dt, time(16, 30), time(19, 30)):
            return True
        
        return False

    def process_5m_candle(self, previous_candle: Candle, current_candle: Candle) -> dict:
        """
        Processes the close of a 5-minute candle to generate trading signals.
        Returns a dict with {"signal": "NONE" | "LONG" | "SHORT", "reason": "...", "entry": ..., "sl": ..., "tp1": ..., "tp2": ...}
        """
        result = {"signal": "NONE"}
        
        if not self.asian_boundaries.is_set:
            return result

        if not self.is_valid_trading_window(current_candle.timestamp):
            # Reset state if we are outside trading windows
            self.last_state = "WAITING"
            self.trigger_candle = None
            return result

        high_bound = self.asian_boundaries.high
        low_bound = self.asian_boundaries.low

        # -----------------------------------------------------------------------------------
        # STATE MACHINE LOGIC FOR SIGNAL GENERATION
        # -----------------------------------------------------------------------------------
        
        # 1. Check for Sweep / Fakeout setups (Reversals)
        if self.last_state == "WAITING":
            # Check if previous candle swept HIGH and closed inside/below
            if previous_candle.high > high_bound and previous_candle.close <= high_bound:
                self.last_state = "SWEEPING_HIGH"
                self.trigger_candle = previous_candle
                logger.info(f"[{current_candle.timestamp}] Swept Asian High. Waiting for confirmation.")
            
            # Check if previous candle swept LOW and closed inside/above
            elif previous_candle.low < low_bound and previous_candle.close >= low_bound:
                self.last_state = "SWEEPING_LOW"
                self.trigger_candle = previous_candle
                logger.info(f"[{current_candle.timestamp}] Swept Asian Low. Waiting for confirmation.")
                
            # Check for pure Breakouts
            elif previous_candle.close > high_bound:
                self.last_state = "BREAKOUT_HIGH"
                self.trigger_candle = previous_candle
                logger.info(f"[{current_candle.timestamp}] Breakout above Asian High. Waiting for confirmation.")
                
            elif previous_candle.close < low_bound:
                self.last_state = "BREAKOUT_LOW"
                self.trigger_candle = previous_candle
                logger.info(f"[{current_candle.timestamp}] Breakout below Asian Low. Waiting for confirmation.")

        # 2. Confirmation Phase
        if self.last_state == "SWEEPING_HIGH":
            # We need current candle to close below the trigger candle's low (Aggressive)
            if self.entry_style == "aggressive" and current_candle.close < self.trigger_candle.low:
                logger.info("Bearish Fakeout Confirmed! Generating SHORT signal.")
                result = self._generate_trade("SHORT", current_candle.close, self.trigger_candle.high, low_bound)
                self.last_state = "WAITING" # Reset after triggering
            elif current_candle.close > self.trigger_candle.high:
                self.last_state = "WAITING" # Invalidation

        elif self.last_state == "SWEEPING_LOW":
            # We need current candle to close above the trigger candle's high (Aggressive)
            if self.entry_style == "aggressive" and current_candle.close > self.trigger_candle.high:
                logger.info("Bullish Fakeout Confirmed! Generating LONG signal.")
                result = self._generate_trade("LONG", current_candle.close, self.trigger_candle.low, high_bound)
                self.last_state = "WAITING" # Reset after triggering
            elif current_candle.close < self.trigger_candle.low:
                self.last_state = "WAITING" # Invalidation

        elif self.last_state == "BREAKOUT_HIGH":
            # Breakout confirmation: current candle clears previous high and stays accepted
            if current_candle.close > self.trigger_candle.high and current_candle.close > high_bound:
                logger.info("Bullish Breakout Confirmed! Generating LONG signal.")
                # SL below the breakout structure (using high_bound as rough structure support)
                result = self._generate_trade("LONG", current_candle.close, high_bound - (current_candle.high - high_bound)*0.5, high_bound + (high_bound - low_bound))
                self.last_state = "WAITING"
            elif current_candle.close < high_bound:
                self.last_state = "WAITING" # Fakeout

        elif self.last_state == "BREAKOUT_LOW":
            # Breakout confirmation: current candle clears previous low and stays accepted
            if current_candle.close < self.trigger_candle.low and current_candle.close < low_bound:
                logger.info("Bearish Breakout Confirmed! Generating SHORT signal.")
                # SL above the breakout structure (using low_bound as rough structure resistance)
                result = self._generate_trade("SHORT", current_candle.close, low_bound + (low_bound - current_candle.low)*0.5, low_bound - (high_bound - low_bound))
                self.last_state = "WAITING"
            elif current_candle.close > low_bound:
                self.last_state = "WAITING" # Fakeout

        return result

    def _generate_trade(self, direction: str, entry: float, sl: float, opposite_boundary: float) -> dict:
        """Calculates TP1 (1:2 R:R) and TP2 (Opposite boundary)."""
        buffer = 0.5 # Small buffer for SL
        
        if direction == "LONG":
            actual_sl = sl - buffer
            risk = entry - actual_sl
            tp1 = entry + (2 * risk)
            tp2 = opposite_boundary
        else:
            actual_sl = sl + buffer
            risk = actual_sl - entry
            tp1 = entry - (2 * risk)
            tp2 = opposite_boundary
            
        return {
            "signal": direction,
            "entry": round(entry, 2),
            "sl": round(actual_sl, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "risk": round(risk, 2)
        }

if __name__ == "__main__":
    # --- MOCK DEMONSTRATION ---
    from datetime import timedelta
    
    logger.info("Starting Gold Strategy Demo...")
    
    # 1. Setup 15m candles to establish Asian boundaries
    start_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0).astimezone(IST_TZ)
    mock_15m = [
        Candle(start_time, 2400.0, 2405.0, 2398.0, 2402.0),
        Candle(start_time + timedelta(minutes=15), 2402.0, 2410.0, 2400.0, 2408.0), # High: 2410
        Candle(start_time + timedelta(minutes=30), 2408.0, 2409.0, 2395.0, 2396.0), # Low: 2395
        Candle(start_time + timedelta(minutes=45), 2396.0, 2400.0, 2396.0, 2399.0)
    ]
    
    engine = GoldStrategyEngine(entry_style="aggressive")
    engine.update_15m_boundaries(mock_15m)
    
    # 2. Setup 5m candles during London session (11:30 AM IST)
    london_start = start_time.replace(hour=11, minute=30)
    
    # Creating a Fakeout Scenario at the Asian High (2410)
    mock_5m = [
        # 11:30 - Approaches High
        Candle(london_start, 2405.0, 2409.0, 2404.0, 2408.0),
        # 11:35 - Sweeps High (2411) but closes inside (2409) -> Bearish Rejection
        Candle(london_start + timedelta(minutes=5), 2408.0, 2412.0, 2407.0, 2409.0),
        # 11:40 - Closes below the breakout candle's low (2407) -> CONFIRMATION
        Candle(london_start + timedelta(minutes=10), 2409.0, 2410.0, 2405.0, 2406.0)
    ]
    
    prev_candle = None
    for c in mock_5m:
        if prev_candle:
            signal = engine.process_5m_candle(prev_candle, c)
            if signal["signal"] != "NONE":
                logger.info(f"*** TRADE SIGNAL EXECUTED ***\n{signal}")
        prev_candle = c
