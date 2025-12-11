"""
Market Data Module for ES Futures Trading
Fetches daily data from Yahoo Finance, calculates VWAP and Volume Profile,
and generates market context for LLM trading decisions.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import logging
import configparser
import json

class MarketDataAnalyzer:
    """Fetches and analyzes market data for ES futures trading."""
    
    def __init__(self, config_file='config.ini'):
        """Initialize the market data analyzer."""
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        
        # Get configuration
        self.es_ticker = self.config.get('MarketData', 'es_ticker', fallback='ES=F')
        self.vix_ticker = self.config.get('MarketData', 'vix_ticker', fallback='^VIX')
        self.historical_days = self.config.getint('MarketData', 'historical_days', fallback=30)
        self.focus_days = self.config.getint('MarketData', 'focus_days', fallback=5)
        self.volume_nodes = self.config.getint('MarketData', 'volume_nodes', fallback=5)
        self.data_folder = self.config.get('MarketData', 'data_folder', fallback='market_data')
        self.enable_intraday = self.config.getboolean('MarketData', 'enable_intraday', fallback=True)
        self.intraday_interval = self.config.get('MarketData', 'intraday_interval', fallback='15m')
        self.intraday_days = self.config.getint('MarketData', 'intraday_days', fallback=5)
        self.intraday_volume_nodes = self.config.getint('MarketData', 'intraday_volume_nodes', fallback=5)
        
        # Create data folder if it doesn't exist
        os.makedirs(self.data_folder, exist_ok=True)
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging
        
    def fetch_data(self, ticker, days=None, max_retries=3):
        """Fetch historical data from Yahoo Finance.
        
        Args:
            ticker: Symbol to fetch (e.g., 'ES=F', '^VIX')
            days: Number of days of historical data (defaults to config value)
            max_retries: Number of retry attempts for network errors
            
        Returns:
            pandas.DataFrame with OHLCV data
        """
        if days is None:
            days = self.historical_days
            
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Fetching {ticker} data from {start_date.date()} to {end_date.date()} (attempt {attempt + 1}/{max_retries})")
                
                # Try to download with timeout
                data = yf.download(ticker, start=start_date, end=end_date, interval='1d', progress=False, timeout=10)
                
                # Check if data is empty
                if isinstance(data, pd.DataFrame) and data.empty:
                    self.logger.warning(f"No data returned for {ticker}")
                    return None
                
                # Flatten multi-level columns if present (happens with single ticker downloads)
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.droplevel(1)
                
                self.logger.info(f"Successfully fetched {len(data)} days of data for {ticker}")
                return data
                
            except Exception as e:
                self.logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {ticker}: {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)  # Wait 2 seconds before retry
                else:
                    self.logger.error(f"All retry attempts failed for {ticker}")
                    return None
        
        return None
    
    def fetch_intraday_data(self, ticker, days=None, interval='15m'):
        """Fetch intraday data from Yahoo Finance.
        
        Args:
            ticker: Symbol to fetch (e.g., 'ES=F')
            days: Number of days of intraday data (max 60 for 15m)
            interval: Time interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h)
            
        Returns:
            pandas.DataFrame with OHLCV data at specified interval
        """
        try:
            if days is None:
                days = self.intraday_days
            
            # Limit days based on interval (Yahoo Finance restrictions)
            max_days = {'1m': 7, '2m': 60, '5m': 60, '15m': 60, '30m': 60, '60m': 730, '90m': 730, '1h': 730}
            days = min(days, max_days.get(interval, 60))
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            self.logger.info(f"Fetching {ticker} intraday data ({interval}) from {start_date.date()} to {end_date.date()}")
            
            data = yf.download(ticker, start=start_date, end=end_date, interval=interval, progress=False, timeout=10)
            
            # Check if data is empty
            if isinstance(data, pd.DataFrame) and data.empty:
                self.logger.warning(f"No intraday data returned for {ticker}")
                return None
            
            # Flatten multi-level columns if present
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)
            
            self.logger.info(f"Successfully fetched {len(data)} {interval} bars for {ticker}")
            return data
            
        except Exception as e:
            self.logger.error(f"Error fetching intraday data for {ticker}: {e}")
            return None
    
    def calculate_vwap(self, df):
        """Calculate VWAP (Volume Weighted Average Price).
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            float: VWAP value
        """
        try:
            typical_price = (df['High'] + df['Low'] + df['Close']) / 3
            vwap = (typical_price * df['Volume']).sum() / df['Volume'].sum()
            return round(vwap, 2)
        except Exception as e:
            self.logger.error(f"Error calculating VWAP: {e}")
            return None
    
    def calculate_volume_profile(self, df, num_levels=5):
        """Calculate Volume Profile - identifies price levels with highest volume.
        
        Args:
            df: DataFrame with OHLCV data
            num_levels: Number of top volume levels to return
            
        Returns:
            list: List of tuples (price_level, volume) sorted by volume
        """
        try:
            # Create price bins (using close prices as reference)
            min_price = df['Low'].min()
            max_price = df['High'].max()
            
            # Create 50 bins across the price range
            bins = np.linspace(min_price, max_price, 50)
            
            # Aggregate volume at each price level
            volume_at_price = {}
            
            for idx, row in df.iterrows():
                # Distribute volume across the day's range
                price_range = row['High'] - row['Low']
                if price_range == 0:
                    price_range = 0.01  # Avoid division by zero
                
                # Find which bin this day's range falls into
                for price in np.linspace(row['Low'], row['High'], 10):
                    bin_idx = np.digitize(price, bins) - 1
                    bin_idx = max(0, min(bin_idx, len(bins) - 2))
                    bin_price = round((bins[bin_idx] + bins[bin_idx + 1]) / 2, 2)
                    
                    if bin_price not in volume_at_price:
                        volume_at_price[bin_price] = 0
                    volume_at_price[bin_price] += row['Volume'] / 10
            
            # Sort by volume and get top levels
            sorted_levels = sorted(volume_at_price.items(), key=lambda x: x[1], reverse=True)
            top_levels = sorted_levels[:num_levels]
            
            # Sort by price for clearer presentation
            top_levels = sorted(top_levels, key=lambda x: x[0], reverse=True)
            
            return top_levels
            
        except Exception as e:
            self.logger.error(f"Error calculating volume profile: {e}")
            return []
    
    def calculate_atr(self, df, period=14, rth_only=True):
        """Calculate Average True Range (ATR).
        
        Args:
            df: DataFrame with OHLCV data
            period: ATR period (default 14)
            rth_only: If True, only use RTH bars (9:30 AM - 4:00 PM ET)
            
        Returns:
            float: Current ATR value
        """
        try:
            df = df.copy()
            
            # Filter to RTH only if requested (RTH = 14:30-21:00 UTC during EST, 13:30-20:00 during EDT)
            # Using 14:30-21:00 UTC as approximation (9:30 AM - 4:00 PM ET)
            if rth_only:
                df['hour'] = df.index.hour
                df['minute'] = df.index.minute
                # RTH in UTC: 14:30 to 21:00 (covers both EST and EDT reasonably)
                rth_mask = (
                    ((df['hour'] == 14) & (df['minute'] >= 30)) |
                    ((df['hour'] >= 15) & (df['hour'] < 21))
                )
                df = df[rth_mask]
                
                if len(df) < period:
                    self.logger.warning(f"Not enough RTH bars for ATR({period}), found {len(df)} bars")
                    return None
            
            df['prev_close'] = df['Close'].shift(1)
            df['tr1'] = df['High'] - df['Low']
            df['tr2'] = abs(df['High'] - df['prev_close'])
            df['tr3'] = abs(df['Low'] - df['prev_close'])
            df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
            df['atr'] = df['true_range'].rolling(window=period).mean()
            
            return round(df['atr'].iloc[-1], 2) if not df['atr'].isna().iloc[-1] else None
        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return None
    
    def calculate_daily_profiles(self, df):
        """Calculate POC, VAH, VAL for each trading day.
        
        Args:
            df: DataFrame with intraday OHLCV data
            
        Returns:
            list: Daily profiles with date, POC, VAH, VAL, high, low, volume
        """
        try:
            df = df.copy()
            df['date'] = df.index.date
            
            daily_profiles = []
            
            for date in df['date'].unique():
                day_data = df[df['date'] == date]
                
                if len(day_data) < 10:  # Skip days with insufficient data
                    continue
                
                # Calculate volume at price for this day
                min_price = day_data['Low'].min()
                max_price = day_data['High'].max()
                
                # Create finer bins for daily profile (0.5 point increments)
                num_bins = max(int((max_price - min_price) / 0.5), 20)
                bins = np.linspace(min_price, max_price, num_bins)
                
                volume_at_price = {}
                for idx, row in day_data.iterrows():
                    for price in np.linspace(row['Low'], row['High'], 10):
                        bin_idx = np.digitize(price, bins) - 1
                        bin_idx = max(0, min(bin_idx, len(bins) - 2))
                        bin_price = round((bins[bin_idx] + bins[bin_idx + 1]) / 2, 2)
                        if bin_price not in volume_at_price:
                            volume_at_price[bin_price] = 0
                        volume_at_price[bin_price] += row['Volume'] / 10
                
                if not volume_at_price:
                    continue
                
                # POC = price with highest volume
                poc = max(volume_at_price.items(), key=lambda x: x[1])[0]
                
                # Value Area (70% of volume)
                total_vol = sum(volume_at_price.values())
                target_vol = total_vol * 0.7
                
                # Build value area from POC outward
                sorted_prices = sorted(volume_at_price.keys())
                poc_idx = sorted_prices.index(poc) if poc in sorted_prices else len(sorted_prices) // 2
                
                va_vol = volume_at_price.get(poc, 0)
                va_low_idx = poc_idx
                va_high_idx = poc_idx
                
                while va_vol < target_vol and (va_low_idx > 0 or va_high_idx < len(sorted_prices) - 1):
                    vol_below = volume_at_price.get(sorted_prices[va_low_idx - 1], 0) if va_low_idx > 0 else 0
                    vol_above = volume_at_price.get(sorted_prices[va_high_idx + 1], 0) if va_high_idx < len(sorted_prices) - 1 else 0
                    
                    if vol_below >= vol_above and va_low_idx > 0:
                        va_low_idx -= 1
                        va_vol += vol_below
                    elif va_high_idx < len(sorted_prices) - 1:
                        va_high_idx += 1
                        va_vol += vol_above
                    else:
                        break
                
                vah = sorted_prices[va_high_idx]
                val = sorted_prices[va_low_idx]
                
                daily_profiles.append({
                    'date': str(date),
                    'poc': round(poc, 2),
                    'vah': round(vah, 2),
                    'val': round(val, 2),
                    'high': round(day_data['High'].max(), 2),
                    'low': round(day_data['Low'].min(), 2),
                    'volume': int(day_data['Volume'].sum())
                })
            
            return daily_profiles[-5:]  # Return last 5 days
            
        except Exception as e:
            self.logger.error(f"Error calculating daily profiles: {e}")
            return []
    
    def calculate_inferred_delta_profile(self, df):
        """Calculate inferred delta at price (volume delta profile).
        
        Note: Yahoo Finance doesn't provide actual buy/sell volume, so we INFER delta
        using price action: close near high suggests buying pressure, close near low suggests selling.
        This is an approximation, not true order flow delta.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            dict: Delta profile with price levels and estimated delta
        """
        try:
            df = df.copy()
            
            min_price = df['Low'].min()
            max_price = df['High'].max()
            bins = np.linspace(min_price, max_price, 30)
            
            delta_at_price = {}
            
            for idx, row in df.iterrows():
                # Estimate delta based on bar direction and position of close
                bar_range = row['High'] - row['Low']
                if bar_range == 0:
                    continue
                
                # Calculate close position within bar (0 = low, 1 = high)
                close_position = (row['Close'] - row['Low']) / bar_range
                
                # Estimate delta: closer to high = more buying, closer to low = more selling
                # Scale from -1 (all selling) to +1 (all buying)
                delta_factor = (close_position - 0.5) * 2
                estimated_delta = row['Volume'] * delta_factor
                
                # Distribute delta across price range
                for price in np.linspace(row['Low'], row['High'], 10):
                    bin_idx = np.digitize(price, bins) - 1
                    bin_idx = max(0, min(bin_idx, len(bins) - 2))
                    bin_price = round((bins[bin_idx] + bins[bin_idx + 1]) / 2, 2)
                    
                    if bin_price not in delta_at_price:
                        delta_at_price[bin_price] = 0
                    delta_at_price[bin_price] += estimated_delta / 10
            
            # Get top positive and negative delta levels
            sorted_by_delta = sorted(delta_at_price.items(), key=lambda x: x[1])
            
            result = {
                'cumulative_delta': round(sum(delta_at_price.values()), 0),
                'top_buying_levels': [(p, round(d, 0)) for p, d in sorted_by_delta[-3:][::-1]],
                'top_selling_levels': [(p, round(d, 0)) for p, d in sorted_by_delta[:3]]
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error calculating delta profile: {e}")
            return {}
    
    def calculate_overnight_session(self, df):
        """Calculate overnight (globex) session levels.
        
        Overnight = 6PM ET to 9:30AM ET (approximated in UTC)
        RTH = 9:30AM ET to 4PM ET
        
        Args:
            df: DataFrame with intraday data (must have timezone-aware index)
            
        Returns:
            dict: Overnight high, low, POC, and RTH open
        """
        try:
            df = df.copy()
            
            # Get the most recent trading day
            df['date'] = df.index.date
            latest_date = df['date'].iloc[-1]
            
            # Get today's data
            today_data = df[df['date'] == latest_date]
            
            if len(today_data) < 5:
                # Not enough data for today, use previous day
                dates = df['date'].unique()
                if len(dates) >= 2:
                    latest_date = dates[-2]
                    today_data = df[df['date'] == latest_date]
            
            # Identify overnight vs RTH based on hour (UTC)
            # RTH is roughly 14:30-21:00 UTC (9:30 AM - 4 PM ET)
            today_data = today_data.copy()
            today_data['hour'] = today_data.index.hour
            
            # Overnight: hours 22-23 (previous day) and 0-14 (current day in UTC)
            overnight_mask = (today_data['hour'] < 14) | (today_data['hour'] >= 22)
            overnight_data = today_data[overnight_mask]
            
            # RTH: hours 14-21 UTC
            rth_mask = (today_data['hour'] >= 14) & (today_data['hour'] < 21)
            rth_data = today_data[rth_mask]
            
            result = {
                'date': str(latest_date),
                'on_high': None,
                'on_low': None,
                'on_poc': None,
                'rth_open': None,
                'globex_range': None
            }
            
            if len(overnight_data) > 0:
                result['on_high'] = round(overnight_data['High'].max(), 2)
                result['on_low'] = round(overnight_data['Low'].min(), 2)
                result['globex_range'] = round(result['on_high'] - result['on_low'], 2)
                
                # Calculate overnight POC
                on_volume_at_price = {}
                for idx, row in overnight_data.iterrows():
                    mid_price = round((row['High'] + row['Low']) / 2, 2)
                    if mid_price not in on_volume_at_price:
                        on_volume_at_price[mid_price] = 0
                    on_volume_at_price[mid_price] += row['Volume']
                
                if on_volume_at_price:
                    result['on_poc'] = max(on_volume_at_price.items(), key=lambda x: x[1])[0]
            
            if len(rth_data) > 0:
                result['rth_open'] = round(rth_data['Open'].iloc[0], 2)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error calculating overnight session: {e}")
            return {}
    
    def calculate_tpo_profile(self, df, tick_size=0.5):
        """Calculate TPO (Time Price Opportunity) profile.
        
        TPO counts how many time periods price visited each level,
        regardless of volume.
        
        Args:
            df: DataFrame with OHLCV data
            tick_size: Price increment for TPO bins (default 0.5)
            
        Returns:
            dict: TPO profile with POC, value area, and single prints
        """
        try:
            df = df.copy()
            
            min_price = df['Low'].min()
            max_price = df['High'].max()
            
            # Create price bins
            num_bins = int((max_price - min_price) / tick_size) + 1
            bins = [round(min_price + i * tick_size, 2) for i in range(num_bins)]
            
            tpo_count = {price: 0 for price in bins}
            
            # Count TPOs (each bar = 1 TPO for each price level it touched)
            for idx, row in df.iterrows():
                for price in bins:
                    if row['Low'] <= price <= row['High']:
                        tpo_count[price] += 1
            
            # TPO POC = price with most TPOs
            tpo_poc = max(tpo_count.items(), key=lambda x: x[1])[0]
            max_tpo = tpo_count[tpo_poc]
            
            # Find single prints (TPO count = 1, indicating fast move through)
            single_prints = [p for p, count in tpo_count.items() if count == 1]
            
            # TPO Value Area (70% of TPOs)
            total_tpos = sum(tpo_count.values())
            target_tpos = total_tpos * 0.7
            
            sorted_prices = sorted(tpo_count.keys())
            poc_idx = sorted_prices.index(tpo_poc)
            
            va_tpos = tpo_count[tpo_poc]
            va_low_idx = poc_idx
            va_high_idx = poc_idx
            
            while va_tpos < target_tpos and (va_low_idx > 0 or va_high_idx < len(sorted_prices) - 1):
                tpo_below = tpo_count.get(sorted_prices[va_low_idx - 1], 0) if va_low_idx > 0 else 0
                tpo_above = tpo_count.get(sorted_prices[va_high_idx + 1], 0) if va_high_idx < len(sorted_prices) - 1 else 0
                
                if tpo_below >= tpo_above and va_low_idx > 0:
                    va_low_idx -= 1
                    va_tpos += tpo_below
                elif va_high_idx < len(sorted_prices) - 1:
                    va_high_idx += 1
                    va_tpos += tpo_above
                else:
                    break
            
            return {
                'tpo_poc': round(tpo_poc, 2),
                'tpo_vah': round(sorted_prices[va_high_idx], 2),
                'tpo_val': round(sorted_prices[va_low_idx], 2),
                'max_tpo_count': max_tpo,
                'single_print_zones': single_prints[:5] if len(single_prints) > 5 else single_prints,  # Limit to 5
                'total_tpos': total_tpos
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating TPO profile: {e}")
            return {}
    
    def calculate_range_extremes(self, df):
        """Calculate 5-day range extremes (multi-day swing high/low).
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            dict: Swing highs, swing lows, and range statistics
        """
        try:
            df = df.copy()
            
            # Overall range
            range_high = df['High'].max()
            range_low = df['Low'].min()
            total_range = range_high - range_low
            
            # Find swing highs (local maxima)
            swing_highs = []
            swing_lows = []
            
            window = 12  # 1 hour for 5m bars
            
            for i in range(window, len(df) - window):
                # Check for swing high
                if df['High'].iloc[i] == df['High'].iloc[i-window:i+window+1].max():
                    swing_highs.append({
                        'price': round(df['High'].iloc[i], 2),
                        'time': str(df.index[i])
                    })
                
                # Check for swing low
                if df['Low'].iloc[i] == df['Low'].iloc[i-window:i+window+1].min():
                    swing_lows.append({
                        'price': round(df['Low'].iloc[i], 2),
                        'time': str(df.index[i])
                    })
            
            # Remove duplicates and keep most significant
            unique_highs = []
            for sh in swing_highs:
                if not any(abs(sh['price'] - uh['price']) < 3 for uh in unique_highs):
                    unique_highs.append(sh)
            
            unique_lows = []
            for sl in swing_lows:
                if not any(abs(sl['price'] - ul['price']) < 3 for ul in unique_lows):
                    unique_lows.append(sl)
            
            # Sort by price
            unique_highs = sorted(unique_highs, key=lambda x: x['price'], reverse=True)[:3]
            unique_lows = sorted(unique_lows, key=lambda x: x['price'])[:3]
            
            return {
                'range_high': round(range_high, 2),
                'range_low': round(range_low, 2),
                'total_range': round(total_range, 2),
                'swing_highs': unique_highs,
                'swing_lows': unique_lows,
                'mid_point': round((range_high + range_low) / 2, 2)
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating range extremes: {e}")
            return {}
    
    def calculate_zone_liquidity(self, key_levels, df):
        """Calculate liquidity summary for each marked zone.
        
        Args:
            key_levels: List of key level dictionaries
            df: DataFrame with OHLCV data
            
        Returns:
            list: Key levels with added liquidity metrics
        """
        try:
            df = df.copy()
            total_volume = df['Volume'].sum()
            
            for level in key_levels:
                zone_high = level['zone_high']
                zone_low = level['zone_low']
                
                # Count touches and volume
                touches = 0
                zone_volume = 0
                avg_reaction = []
                time_at_level = 0
                
                for i in range(len(df)):
                    row = df.iloc[i]
                    if row['Low'] <= zone_high and row['High'] >= zone_low:
                        touches += 1
                        zone_volume += row['Volume']
                        time_at_level += 5  # 5 minutes per bar
                        
                        # Measure reaction
                        if i < len(df) - 3:
                            future = df.iloc[i+1:i+4]
                            if len(future) > 0:
                                move = max(
                                    abs(future['High'].max() - level['level']),
                                    abs(future['Low'].min() - level['level'])
                                )
                                avg_reaction.append(move)
                
                level['liquidity'] = {
                    'touches': touches,
                    'time_at_level_mins': time_at_level,
                    'avg_reaction_pts': round(np.mean(avg_reaction), 2) if avg_reaction else 0,
                    'volume_concentration': round((zone_volume / total_volume) * 100, 2) if total_volume > 0 else 0
                }
            
            return key_levels
            
        except Exception as e:
            self.logger.error(f"Error calculating zone liquidity: {e}")
            return key_levels
    
    def generate_extended_analysis(self, df):
        """Generate comprehensive market analysis from intraday data.
        
        Args:
            df: DataFrame with 5-minute OHLCV data
            
        Returns:
            dict: Complete analysis including all calculated metrics
        """
        try:
            analysis = {}
            
            # ATR(14)
            atr = self.calculate_atr(df, 14)
            analysis['atr_14'] = atr
            
            # Daily profiles
            daily_profiles = self.calculate_daily_profiles(df)
            analysis['daily_profiles'] = daily_profiles
            
            # Inferred delta profile (estimated from price action, not actual order flow)
            delta = self.calculate_inferred_delta_profile(df)
            analysis['inferred_delta_profile'] = delta
            
            # Overnight session
            overnight = self.calculate_overnight_session(df)
            analysis['overnight_session'] = overnight
            
            # TPO profile
            tpo = self.calculate_tpo_profile(df)
            analysis['tpo_profile'] = tpo
            
            # Range extremes
            extremes = self.calculate_range_extremes(df)
            analysis['range_extremes'] = extremes
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error generating extended analysis: {e}")
            return {}
    
    def save_extended_analysis(self, analysis):
        """Save extended analysis to JSON file.
        
        Args:
            analysis: Dictionary with all analysis data
        """
        try:
            filename = os.path.join(self.data_folder, f"extended_analysis_{datetime.now().strftime('%Y%m%d')}.json")
            
            output = {
                'generated_at': datetime.now().isoformat(),
                **analysis
            }
            
            with open(filename, 'w') as f:
                json.dump(output, f, indent=2, default=str)
            
            self.logger.info(f"Saved extended analysis to {filename}")
            
        except Exception as e:
            self.logger.error(f"Error saving extended analysis: {e}")
    
    def analyze_structure_zones(self, df):
        """Analyze 5-minute bars to identify key structure zones.
        
        Step 1: Compress bars into candidate zones (HVN clusters, swing points, volatility shifts)
        Step 2: Filter out noise to leave only macro levels
        
        Args:
            df: DataFrame with 5-minute OHLCV data
            
        Returns:
            list: List of key level dictionaries with level, zone_width, type, reason
        """
        try:
            if df is None or df.empty or len(df) < 20:
                self.logger.warning("Insufficient data for structure zone analysis")
                return []
            
            # Step 1: Identify candidate zones (target 6-10)
            candidates = []
            
            # 1a. High Volume Node clusters (30-90 min = 6-18 bars for 5m)
            hvn_zones = self._identify_hvn_clusters(df)
            candidates.extend(hvn_zones)
            
            # 1b. Sharp rejection bars (swing highs/lows)
            swing_points = self._identify_swing_points(df)
            candidates.extend(swing_points)
            
            # 1c. Volatility shift areas (compression → expansion)
            volatility_zones = self._identify_volatility_shifts(df)
            candidates.extend(volatility_zones)
            
            self.logger.info(f"Identified {len(candidates)} candidate structure zones")
            
            # Step 2: Filter noise to get macro levels (target 3-6)
            key_levels = self._filter_noise(candidates, df)
            
            self.logger.info(f"Filtered to {len(key_levels)} key structure levels")
            
            return key_levels
            
        except Exception as e:
            self.logger.error(f"Error analyzing structure zones: {e}")
            return []
    
    def _identify_hvn_clusters(self, df):
        """Identify High Volume Node clusters (30-90 min balance areas).
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            list: Candidate zones from HVN analysis
        """
        candidates = []
        
        try:
            # Calculate rolling volume (6-18 bars = 30-90 min for 5m data)
            df = df.copy()
            df['vol_ma'] = df['Volume'].rolling(window=12).mean()
            df['vol_std'] = df['Volume'].rolling(window=12).std()
            df['vol_zscore'] = (df['Volume'] - df['vol_ma']) / df['vol_std'].replace(0, 1)
            
            # Find high volume clusters (z-score > 1.5)
            high_vol_mask = df['vol_zscore'] > 1.5
            
            # Group consecutive high volume bars
            df['hv_group'] = (~high_vol_mask).cumsum()
            df['hv_group'] = df['hv_group'].where(high_vol_mask, np.nan)
            
            # Process each cluster
            for group_id in df['hv_group'].dropna().unique():
                cluster = df[df['hv_group'] == group_id]
                
                if len(cluster) >= 6:  # At least 30 minutes
                    cluster_high = cluster['High'].max()
                    cluster_low = cluster['Low'].min()
                    cluster_mid = (cluster_high + cluster_low) / 2
                    zone_width = min(cluster_high - cluster_low, 8.0)  # Cap at 8 points
                    total_volume = cluster['Volume'].sum()
                    duration_mins = len(cluster) * 5
                    
                    candidates.append({
                        'level': round(cluster_mid, 2),
                        'zone_high': round(cluster_mid + zone_width / 2, 2),
                        'zone_low': round(cluster_mid - zone_width / 2, 2),
                        'type': 'Major HVN / Balance POC',
                        'reason': f'{duration_mins} min balance + heavy volume rotation',
                        'volume': total_volume,
                        'bar_count': len(cluster),
                        'tests': 1  # Will be updated in filtering
                    })
            
        except Exception as e:
            self.logger.warning(f"Error in HVN cluster identification: {e}")
        
        return candidates
    
    def _identify_swing_points(self, df):
        """Identify sharp rejection bars that define swing highs/lows.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            list: Candidate zones from swing point analysis
        """
        candidates = []
        
        try:
            df = df.copy()
            
            # Calculate bar characteristics
            df['range'] = df['High'] - df['Low']
            df['body'] = abs(df['Close'] - df['Open'])
            df['upper_wick'] = df['High'] - df[['Open', 'Close']].max(axis=1)
            df['lower_wick'] = df[['Open', 'Close']].min(axis=1) - df['Low']
            df['range_ma'] = df['range'].rolling(window=20).mean()
            
            # Identify rejection bars (large wicks relative to body)
            for i in range(5, len(df) - 5):
                row = df.iloc[i]
                
                # Skip if range is too small
                if row['range'] < 2.0:
                    continue
                
                # Check for swing high (large upper wick rejection)
                if row['upper_wick'] > row['body'] * 1.5 and row['upper_wick'] > 1.5:
                    # Verify it's a local high
                    local_high = df['High'].iloc[max(0, i-5):min(len(df), i+6)].max()
                    if row['High'] >= local_high * 0.999:
                        zone_width = min(row['upper_wick'], 5.0)
                        candidates.append({
                            'level': round(row['High'], 2),
                            'zone_high': round(row['High'], 2),
                            'zone_low': round(row['High'] - zone_width, 2),
                            'type': 'Swing Failure High',
                            'reason': 'Aggressive wick rejection + absorption',
                            'volume': row['Volume'],
                            'bar_count': 1,
                            'tests': 1
                        })
                
                # Check for swing low (large lower wick rejection)
                if row['lower_wick'] > row['body'] * 1.5 and row['lower_wick'] > 1.5:
                    # Verify it's a local low
                    local_low = df['Low'].iloc[max(0, i-5):min(len(df), i+6)].min()
                    if row['Low'] <= local_low * 1.001:
                        zone_width = min(row['lower_wick'], 5.0)
                        candidates.append({
                            'level': round(row['Low'], 2),
                            'zone_high': round(row['Low'] + zone_width, 2),
                            'zone_low': round(row['Low'], 2),
                            'type': 'Swing Failure Low',
                            'reason': 'Aggressive wick rejection + buying absorption',
                            'volume': row['Volume'],
                            'bar_count': 1,
                            'tests': 1
                        })
            
        except Exception as e:
            self.logger.warning(f"Error in swing point identification: {e}")
        
        return candidates
    
    def _identify_volatility_shifts(self, df):
        """Identify areas where volatility shifts from compression to expansion.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            list: Candidate zones from volatility analysis
        """
        candidates = []
        
        try:
            df = df.copy()
            
            # Calculate ATR-like volatility measure
            df['range'] = df['High'] - df['Low']
            df['vol_short'] = df['range'].rolling(window=6).mean()   # 30 min
            df['vol_long'] = df['range'].rolling(window=24).mean()   # 2 hours
            df['vol_ratio'] = df['vol_short'] / df['vol_long'].replace(0, 1)
            
            # Find compression zones (low volatility) followed by expansion
            for i in range(30, len(df) - 6):
                # Check for compression (vol_ratio < 0.7 for at least 6 bars)
                compression_window = df['vol_ratio'].iloc[i-6:i]
                if compression_window.mean() < 0.7:
                    # Check for expansion after
                    expansion_window = df['vol_ratio'].iloc[i:i+6]
                    if expansion_window.mean() > 1.3:
                        # This is a decision point
                        breakout_bar = df.iloc[i]
                        
                        # Determine direction of breakout
                        zone_width = min(breakout_bar['range'], 4.0)
                        if breakout_bar['Close'] > breakout_bar['Open']:
                            level = breakout_bar['Low']  # Support became launch point
                            zone_type = 'Break-Hold-Continuation Base'
                            zone_high = level + zone_width
                            zone_low = level
                        else:
                            level = breakout_bar['High']  # Resistance broke down
                            zone_type = 'Failed Breakout / Trap Zone'
                            zone_high = level
                            zone_low = level - zone_width
                        
                        candidates.append({
                            'level': round(level, 2),
                            'zone_high': round(zone_high, 2),
                            'zone_low': round(zone_low, 2),
                            'type': zone_type,
                            'reason': 'Compression → expansion decision point',
                            'volume': breakout_bar['Volume'],
                            'bar_count': 6,
                            'tests': 1
                        })
            
        except Exception as e:
            self.logger.warning(f"Error in volatility shift identification: {e}")
        
        return candidates
    
    def _filter_noise(self, candidates, df):
        """Filter out small S/R noise, keeping only macro levels.
        
        Removes levels that:
        - Only tested once
        - Reactions < 4 points
        - Created by only one 5-min bar (unless high volume)
        - No volume anomaly
        
        Args:
            candidates: List of candidate zones
            df: Original DataFrame for validation
            
        Returns:
            list: Filtered key levels (target 3-6)
        """
        if not candidates:
            return []
        
        try:
            df = df.copy()
            avg_volume = df['Volume'].mean()
            total_volume = df['Volume'].sum()  # Total volume for the entire period
            
            filtered = []
            
            for candidate in candidates:
                level = candidate['level']
                zone_high = candidate['zone_high']
                zone_low = candidate['zone_low']
                
                # Count how many times price tested this level and track volume
                tests = 0
                reactions = []
                zone_volume = 0  # Volume that interacted with this zone
                
                for i in range(1, len(df) - 1):
                    row = df.iloc[i]
                    
                    # Check if price touched the zone
                    if row['Low'] <= zone_high and row['High'] >= zone_low:
                        tests += 1
                        zone_volume += row['Volume']  # Add volume that touched this zone
                        
                        # Measure reaction (move away from level)
                        future_bars = df.iloc[i+1:min(i+7, len(df))]
                        if len(future_bars) > 0:
                            if row['Close'] > level:
                                reaction = future_bars['High'].max() - level
                            else:
                                reaction = level - future_bars['Low'].min()
                            reactions.append(reaction)
                
                # Update test count and volume percent
                candidate['tests'] = tests
                candidate['zone_volume'] = zone_volume
                candidate['total_volume_percent'] = round((zone_volume / total_volume) * 100, 2) if total_volume > 0 else 0
                
                # Apply filter conditions
                # Condition 1: Must be tested more than once (unless HVN cluster)
                if tests < 2 and candidate['type'] not in ['Major HVN / Balance POC']:
                    continue
                
                # Condition 2: Reactions must be >= 4 points on average
                if reactions and np.mean(reactions) < 4.0:
                    continue
                
                # Condition 3: Single bar levels need high volume
                if candidate['bar_count'] == 1 and candidate['volume'] < avg_volume * 1.5:
                    continue
                
                # Condition 4: Must have volume anomaly (volume > avg)
                if candidate['volume'] < avg_volume * 0.8:
                    continue
                
                # Calculate confidence score for sorting
                confidence = (
                    tests * 0.3 +
                    (np.mean(reactions) if reactions else 0) * 0.1 +
                    (candidate['volume'] / avg_volume) * 0.2 +
                    candidate['bar_count'] * 0.05
                )
                candidate['confidence'] = confidence
                
                filtered.append(candidate)
            
            # Sort by confidence and take top 6
            filtered = sorted(filtered, key=lambda x: x.get('confidence', 0), reverse=True)
            
            # Merge nearby levels (within 6 points)
            merged = []
            for level in filtered:
                is_duplicate = False
                for existing in merged:
                    if abs(level['level'] - existing['level']) < 6.0:
                        is_duplicate = True
                        # Merge: keep the higher confidence one, expand zone boundaries
                        if level.get('confidence', 0) > existing.get('confidence', 0):
                            # Expand zone to cover both
                            level['zone_high'] = max(level['zone_high'], existing['zone_high'])
                            level['zone_low'] = min(level['zone_low'], existing['zone_low'])
                            merged.remove(existing)
                            merged.append(level)
                        else:
                            # Expand zone to cover both
                            existing['zone_high'] = max(level['zone_high'], existing['zone_high'])
                            existing['zone_low'] = min(level['zone_low'], existing['zone_low'])
                        break
                if not is_duplicate:
                    merged.append(level)
            
            # Recalculate volume for merged zones (avoid double-counting)
            for level in merged:
                zone_high = level['zone_high']
                zone_low = level['zone_low']
                zone_volume = 0
                for i in range(len(df)):
                    row = df.iloc[i]
                    if row['Low'] <= zone_high and row['High'] >= zone_low:
                        zone_volume += row['Volume']
                level['zone_volume'] = zone_volume
                level['total_volume_percent'] = round((zone_volume / total_volume) * 100, 2) if total_volume > 0 else 0
            
            # Return top 3-6 levels
            result = merged[:6]
            
            # Clean up internal fields before returning (keep level, zone_high, zone_low, type, reason, total_volume_percent)
            for level in result:
                level.pop('volume', None)
                level.pop('zone_volume', None)
                level.pop('bar_count', None)
                level.pop('tests', None)
                level.pop('confidence', None)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error filtering noise: {e}")
            return candidates[:6]  # Fallback to first 6 candidates
    
    def save_key_levels(self, key_levels):
        """Save key levels to JSON file.
        
        Args:
            key_levels: List of key level dictionaries
        """
        try:
            filename = os.path.join(self.data_folder, f"key_levels_{datetime.now().strftime('%Y%m%d')}.json")
            
            output = {
                'generated_at': datetime.now().isoformat(),
                'key_levels': key_levels
            }
            
            with open(filename, 'w') as f:
                json.dump(output, f, indent=2)
            
            self.logger.info(f"Saved key levels to {filename}")
            
        except Exception as e:
            self.logger.error(f"Error saving key levels: {e}")
    
    def save_data(self, ticker, df):
        """Save data to CSV file.
        
        Args:
            ticker: Symbol name (used in filename)
            df: DataFrame to save
        """
        try:
            # Clean ticker name for filename
            clean_ticker = ticker.replace('^', '').replace('=', '_')
            filename = os.path.join(self.data_folder, f"{clean_ticker}_{datetime.now().strftime('%Y%m%d')}.csv")
            
            df.to_csv(filename)
            self.logger.info(f"Saved data to {filename}")
            
        except Exception as e:
            self.logger.error(f"Error saving data: {e}")
    
    def save_intraday_data(self, ticker, df, interval):
        """Save intraday data to CSV file.
        
        Args:
            ticker: Symbol name (used in filename)
            df: DataFrame to save
            interval: Interval string (e.g., '15m')
        """
        try:
            # Clean ticker name for filename
            clean_ticker = ticker.replace('^', '').replace('=', '_')
            filename = os.path.join(self.data_folder, f"{clean_ticker}_{interval}_{datetime.now().strftime('%Y%m%d')}.csv")
            
            df.to_csv(filename)
            self.logger.info(f"Saved intraday data to {filename}")
            
        except Exception as e:
            self.logger.error(f"Error saving intraday data: {e}")
    
    def generate_market_context(self, force_refresh=False):
        """Generate formatted market context for LLM prompts.
        
        Args:
            force_refresh: If True, fetch fresh data. If False, use cached data if available today.
                          Note: Caching is now handled by screenshot_uploader.py, not here.
            
        Returns:
            str: Formatted market context string
        """
        try:
            # Fetch ES data
            es_data = self.fetch_data(self.es_ticker)
            if es_data is None or es_data.empty:
                self.logger.error("Failed to fetch ES data from Yahoo Finance")
                return "Market data unavailable - Yahoo Finance connection failed. Continue with manual analysis."
            
            # Fetch VIX data
            vix_data = self.fetch_data(self.vix_ticker, days=5)
            
            # Save full historical data
            self.save_data(self.es_ticker, es_data)
            if vix_data is not None and not vix_data.empty:
                self.save_data(self.vix_ticker, vix_data)
            
            # Focus on recent days for volume profile
            focus_data = es_data.tail(self.focus_days)
            
            # Calculate metrics (ensure we get scalar values, not Series)
            current_price = float(es_data['Close'].iloc[-1])
            open_price = float(es_data['Open'].iloc[-1])
            daily_change = current_price - open_price
            daily_change_pct = (daily_change / open_price) * 100
            
            # High/Low for the day
            daily_high = float(es_data['High'].iloc[-1])
            daily_low = float(es_data['Low'].iloc[-1])
            
            # Gap detection (compare today's open to previous close)
            gap_info = ""
            if len(es_data) >= 2:
                prev_close = float(es_data['Close'].iloc[-2])
                gap_size = open_price - prev_close
                gap_pct = (gap_size / prev_close) * 100
                
                if abs(gap_size) >= 5:  # Significant gap threshold (5 points)
                    gap_direction = "GAP UP" if gap_size > 0 else "GAP DOWN"
                    gap_info = f"{gap_direction}: {abs(gap_size):.2f} pts ({abs(gap_pct):.2f}%) from previous close {prev_close:.2f}"
                elif abs(gap_size) >= 2:  # Minor gap
                    gap_direction = "Minor gap up" if gap_size > 0 else "Minor gap down"
                    gap_info = f"{gap_direction}: {abs(gap_size):.2f} pts ({abs(gap_pct):.2f}%)"
            
            # VWAP (using focus period)
            vwap = float(self.calculate_vwap(focus_data))
            vwap_bias = "bullish" if current_price > vwap else "bearish"
            vwap_diff = current_price - vwap
            
            # Volume Profile
            volume_profile = self.calculate_volume_profile(focus_data, self.volume_nodes)
            poc_price = volume_profile[0][0] if volume_profile else current_price  # Point of Control
            
            # VIX analysis
            vix_info = ""
            if vix_data is not None and not vix_data.empty:
                current_vix = float(vix_data['Close'].iloc[-1])
                prev_vix = float(vix_data['Close'].iloc[-2]) if len(vix_data) > 1 else current_vix
                vix_change = current_vix - prev_vix
                vix_change_pct = (vix_change / prev_vix) * 100
                
                if current_vix < 15:
                    vix_env = "Low volatility (complacent)"
                elif current_vix < 20:
                    vix_env = "Normal volatility"
                elif current_vix < 30:
                    vix_env = "Elevated volatility"
                else:
                    vix_env = "High volatility (fear)"
                
                vix_info = f"VIX: {current_vix:.2f} ({vix_change_pct:+.1f}%) - {vix_env}"
            
            # Recent trend (5-day)
            if len(focus_data) >= 5:
                five_day_start_price = float(focus_data['Close'].iloc[0])
                five_day_change = current_price - five_day_start_price
                five_day_pct = (five_day_change / five_day_start_price) * 100
                trend = "uptrend" if five_day_change > 0 else "downtrend"
            else:
                five_day_pct = 0
                trend = "neutral"
            
            # Format context
            context = f"""Market Context ({datetime.now().strftime('%b %d, %Y')}):
ES: Open {open_price:.2f}, Current {current_price:.2f} ({daily_change:+.2f}, {daily_change_pct:+.2f}%), Range {daily_low:.2f}-{daily_high:.2f}"""
            
            # Add gap info if present
            if gap_info:
                context += f"\n{gap_info}"
            
            context += f"""
5-Day Trend: {trend.upper()} ({five_day_pct:+.2f}%)
VWAP ({self.focus_days}-day): {vwap:.2f} | Price is {abs(vwap_diff):.2f} pts {vwap_bias.upper()} of VWAP
{vix_info}

Volume Profile (Top {self.volume_nodes} levels from past {self.focus_days} days):"""

            # Add volume profile levels
            for i, (price, volume) in enumerate(volume_profile, 1):
                context += f"\n  {i}. {price:.2f} pts"
                if i == 1:
                    context += " (POC - Point of Control)"
            
            # Intraday Volume Profile
            if self.enable_intraday:
                # Fetch intraday data using configured days
                intraday_data = self.fetch_intraday_data(self.es_ticker, days=self.intraday_days, interval=self.intraday_interval)
                if intraday_data is not None and not intraday_data.empty:
                    # Save intraday data
                    self.save_intraday_data(self.es_ticker, intraday_data, self.intraday_interval)
                    
                    # Calculate intraday VWAP (across all fetched days)
                    intraday_vwap = float(self.calculate_vwap(intraday_data))
                    intraday_vwap_diff = current_price - intraday_vwap
                    intraday_vwap_bias = "bullish" if current_price > intraday_vwap else "bearish"
                    
                    # Calculate intraday volume profile (across all fetched days)
                    intraday_volume_profile = self.calculate_volume_profile(intraday_data, self.intraday_volume_nodes)
                    
                    context += f"\n\nIntraday {self.intraday_interval} Volume Profile ({self.intraday_days} days, {len(intraday_data)} bars):"
                    context += f"\nIntraday VWAP: {intraday_vwap:.2f} | Price is {abs(intraday_vwap_diff):.2f} pts {intraday_vwap_bias.upper()}"
                    context += f"\nTop {self.intraday_volume_nodes} High Volume Zones:"
                    
                    for i, (price, volume) in enumerate(intraday_volume_profile, 1):
                        volume_pct = (volume / intraday_data['Volume'].sum()) * 100
                        context += f"\n  {i}. {price:.2f} pts ({volume_pct:.1f}% of volume)"
                        if i == 1:
                            context += " (Intraday POC)"
                    
                    # Analyze structure zones from intraday data
                    key_levels = self.analyze_structure_zones(intraday_data)
                    
                    if key_levels:
                        # Add liquidity summaries to key levels
                        key_levels = self.calculate_zone_liquidity(key_levels, intraday_data)
                        
                        # Save to JSON
                        self.save_key_levels(key_levels)
                        
                        # Add to context
                        context += f"\n\nKey Structure Zones ({len(key_levels)} macro levels):"
                        for i, level in enumerate(key_levels, 1):
                            context += f"\n  {i}. {level['level']:.2f} pts ({level['zone_low']:.2f}-{level['zone_high']:.2f}) - {level['type']} ({level['total_volume_percent']:.1f}% vol)"
                            context += f"\n     Reason: {level['reason']}"
                            if 'liquidity' in level:
                                liq = level['liquidity']
                                context += f"\n     Liquidity: {liq['touches']} touches, {liq['time_at_level_mins']}min at level, {liq['avg_reaction_pts']:.1f}pt avg reaction"
                    
                    # Generate extended analysis
                    extended = self.generate_extended_analysis(intraday_data)
                    
                    # Save extended analysis
                    self.save_extended_analysis(extended)
                    
                    # ATR (RTH only)
                    if extended.get('atr_14'):
                        context += f"\n\n5m ATR(14) RTH: {extended['atr_14']:.2f} pts"
                    
                    # Range Extremes
                    if extended.get('range_extremes'):
                        re = extended['range_extremes']
                        context += f"\n\n5-Day Range Extremes:"
                        context += f"\n  High: {re['range_high']:.2f} | Low: {re['range_low']:.2f} | Range: {re['total_range']:.2f} pts | Mid: {re['mid_point']:.2f}"
                        if re.get('swing_highs'):
                            swing_high_str = ', '.join([f"{sh['price']:.2f}" for sh in re['swing_highs']])
                            context += f"\n  Swing Highs: {swing_high_str}"
                        if re.get('swing_lows'):
                            swing_low_str = ', '.join([f"{sl['price']:.2f}" for sl in re['swing_lows']])
                            context += f"\n  Swing Lows: {swing_low_str}"
                    
                    # Overnight Session
                    if extended.get('overnight_session') and extended['overnight_session'].get('on_high'):
                        on = extended['overnight_session']
                        context += f"\n\nOvernight/Globex Session ({on['date']}):"
                        context += f"\n  ON High: {on['on_high']:.2f} | ON Low: {on['on_low']:.2f} | Range: {on['globex_range']:.2f} pts"
                        if on.get('on_poc'):
                            context += f" | ON POC: {on['on_poc']:.2f}"
                        if on.get('rth_open'):
                            context += f"\n  RTH Open: {on['rth_open']:.2f}"
                    
                    # Daily Profiles (last 5 days)
                    if extended.get('daily_profiles'):
                        context += f"\n\nDaily Session Profiles (POC/VAH/VAL):"
                        for dp in extended['daily_profiles']:
                            context += f"\n  {dp['date']}: POC {dp['poc']:.2f} | VAH {dp['vah']:.2f} | VAL {dp['val']:.2f} | Range {dp['low']:.2f}-{dp['high']:.2f}"
                    
                    # Inferred Delta Profile
                    if extended.get('inferred_delta_profile') and extended['inferred_delta_profile'].get('cumulative_delta') is not None:
                        delta = extended['inferred_delta_profile']
                        delta_bias = "BUYING" if delta['cumulative_delta'] > 0 else "SELLING"
                        context += f"\n\nInferred Delta Profile (from price action, not order flow):"
                        context += f"\n  Cumulative Delta: {delta['cumulative_delta']:+.0f} ({delta_bias} pressure)"
                        if delta.get('top_buying_levels'):
                            buying_str = ', '.join([f"{p:.2f}" for p, d in delta['top_buying_levels']])
                            context += f"\n  Top Buying Levels: {buying_str}"
                        if delta.get('top_selling_levels'):
                            selling_str = ', '.join([f"{p:.2f}" for p, d in delta['top_selling_levels']])
                            context += f"\n  Top Selling Levels: {selling_str}"
                    
                    # TPO Profile
                    if extended.get('tpo_profile') and extended['tpo_profile'].get('tpo_poc'):
                        tpo = extended['tpo_profile']
                        context += f"\n\nTPO Profile:"
                        context += f"\n  TPO POC: {tpo['tpo_poc']:.2f} | TPO VAH: {tpo['tpo_vah']:.2f} | TPO VAL: {tpo['tpo_val']:.2f}"
                        if tpo.get('single_print_zones') and len(tpo['single_print_zones']) > 0:
                            single_prints_str = ', '.join([f"{p:.2f}" for p in tpo['single_print_zones'][:5]])
                            context += f"\n  Single Prints (fast move): {single_prints_str}"
            
            # Add daily key levels
            context += f"\n\nDaily Key Levels: Support {daily_low:.2f}, Resistance {daily_high:.2f}"
            
            self.logger.info("Generated market context successfully")
            return context
            
        except Exception as e:
            self.logger.error(f"Error generating market context: {e}")
            return f"Error generating market context: {str(e)}"
    
    def get_latest_price(self):
        """Get the latest ES price.
        
        Returns:
            float: Latest close price or None
        """
        try:
            data = self.fetch_data(self.es_ticker, days=2)
            if data is not None and not data.empty:
                return data['Close'].iloc[-1]
            return None
        except Exception as e:
            self.logger.error(f"Error getting latest price: {e}")
            return None


def main():
    """Main function for standalone execution."""
    print("=" * 70)
    print("ES Futures Market Data Analyzer")
    print("=" * 70)
    
    analyzer = MarketDataAnalyzer()
    
    print("\nFetching and analyzing market data...")
    context = analyzer.generate_market_context(force_refresh=True)
    
    print("\n" + "=" * 70)
    print("MARKET CONTEXT FOR TODAY")
    print("=" * 70)
    print(context)
    print("=" * 70)
    
    print(f"\nData saved to: {analyzer.data_folder}/")
    print("Context is ready to be used in your trading system.")


if __name__ == "__main__":
    main()

