import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import time
import logging
import pytz
from gold_strategy import GoldStrategyEngine, Candle

logger = logging.getLogger("mt5_bot")
logging.basicConfig(level=logging.INFO)

IST_TZ = pytz.timezone('Asia/Kolkata')
SYMBOL = "XAUUSD" # The standard symbol for Gold, might be "XAUUSDm" or "GOLD" depending on the broker

class MT5GoldBot:
    def __init__(self, risk_per_trade: float = 100.0, entry_style: str = "aggressive"):
        self.engine = GoldStrategyEngine(risk_per_trade=risk_per_trade, entry_style=entry_style)
        self.last_processed_time = None
        
    def initialize_mt5(self) -> bool:
        """Initialize the connection to the MT5 terminal"""
        if not mt5.initialize():
            logger.error(f"initialize() failed, error code = {mt5.last_error()}")
            return False
            
        # Ensure symbol is visible
        if not mt5.symbol_select(SYMBOL, True):
            logger.error(f"Failed to select symbol {SYMBOL}")
            mt5.shutdown()
            return False
            
        logger.info(f"Successfully connected to MT5. Trading {SYMBOL}")
        return True

    def _convert_mt5_rates_to_candles(self, rates) -> list[Candle]:
        candles = []
        for r in rates:
            # MT5 timestamps are in UTC. We need to parse them as UTC.
            dt_utc = datetime.fromtimestamp(r['time'], tz=pytz.UTC)
            candles.append(Candle(
                timestamp=dt_utc,
                open=r['open'],
                high=r['high'],
                low=r['low'],
                close=r['close']
            ))
        return candles

    def fetch_data(self):
        """Fetches 15m and 5m candles and feeds them to the strategy engine"""
        # 1. Fetch today's 15m candles to establish Asian boundaries
        # Fetching 50 bars should be enough to cover the Asian session for the current day
        rates_15m = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 50)
        if rates_15m is not None and len(rates_15m) > 0:
            candles_15m = self._convert_mt5_rates_to_candles(rates_15m)
            self.engine.update_15m_boundaries(candles_15m)
            
        # 2. Fetch the last two 5m candles for signal processing
        rates_5m = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 3)
        if rates_5m is not None and len(rates_5m) >= 3:
            candles_5m = self._convert_mt5_rates_to_candles(rates_5m)
            
            # The last candle in MT5 is the currently forming candle (index -1).
            # We must process fully completed candles to prevent false signals, so we use -3 and -2.
            previous_candle = candles_5m[-3] 
            current_candle = candles_5m[-2] # The most recently closed candle
            
            # Prevent processing the same candle multiple times and spamming trades
            if self.last_processed_time == current_candle.timestamp:
                return
            self.last_processed_time = current_candle.timestamp
            
            signal = self.engine.process_5m_candle(previous_candle, current_candle)
            
            if signal["signal"] != "NONE":
                logger.info(f"!!! SIGNAL GENERATED !!! : {signal}")
                self.execute_trade(signal)

    def execute_trade(self, signal: dict):
        """Executes a paper trade in MT5 based on the signal"""
        logger.info(f"Executing MT5 Trade: {signal}")
        
        # Determine order type
        if signal["signal"] == "LONG":
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(SYMBOL).ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(SYMBOL).bid
            
        # Calculate lot size based on risk
        # This is simplified. Real lot calculation requires checking symbol tick_value and lot_step
        # MT5 standard lot = 100 ounces for Gold. 
        # Risk = (Entry - SL) * Lot * 100
        # Lot = Risk / ((Entry - SL) * 100)
        
        risk_dollars = signal["risk"]
        sl_points = abs(signal["entry"] - signal["sl"])
        
        if sl_points > 0:
            raw_lot = self.engine.risk_per_trade / (sl_points * 100)
            # Round to nearest 0.01 lot
            lot = round(raw_lot, 2)
            lot = max(0.01, lot) # Minimum 0.01
        else:
            lot = 0.01

        # Dynamically determine the supported filling mode for this broker
        symbol_info = mt5.symbol_info(SYMBOL)
        filling_type = mt5.ORDER_FILLING_FOK # Default to FOK
        if symbol_info is not None:
            if symbol_info.filling_mode & mt5.SYMBOL_FILLING_IOC:
                filling_type = mt5.ORDER_FILLING_IOC
            elif symbol_info.filling_mode & mt5.SYMBOL_FILLING_FOK:
                filling_type = mt5.ORDER_FILLING_FOK
            else:
                filling_type = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": float(signal["sl"]),
            "tp": float(signal["tp1"]),
            "deviation": 20,
            "magic": 123456, # Unique ID for our bot's trades
            "comment": "Gold Strategy",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }
        
        # Send order
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed, retcode={result.retcode}")
            # print error details
            logger.error(result._asdict())
        else:
            logger.info(f"Order successfully placed! Ticket: {result.order}")

    def run(self):
        """Main bot loop"""
        if not self.initialize_mt5():
            return
            
        logger.info("Bot is running. Waiting for valid trading windows...")
        try:
            while True:
                now_ist = datetime.now(IST_TZ)
                
                # We only fetch and process data if we are inside a valid trading window
                if self.engine.is_valid_trading_window(now_ist):
                    self.fetch_data()
                
                # Sleep until the next 5-minute interval to save resources
                # For a real bot, we might sleep exactly until the next 5m close
                time.sleep(10)
                
        except KeyboardInterrupt:
            logger.info("Shutting down bot...")
            mt5.shutdown()

if __name__ == "__main__":
    bot = MT5GoldBot(risk_per_trade=100.0) # $100 risk per trade
    bot.run()
