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
            
            # Intraday Volume Profile (15-minute)
            if self.enable_intraday:
                intraday_data = self.fetch_intraday_data(self.es_ticker, self.intraday_days, self.intraday_interval)
                if intraday_data is not None and not intraday_data.empty:
                    # Save intraday data
                    self.save_intraday_data(self.es_ticker, intraday_data, self.intraday_interval)
                    
                    # Calculate intraday VWAP
                    intraday_vwap = float(self.calculate_vwap(intraday_data))
                    intraday_vwap_diff = current_price - intraday_vwap
                    intraday_vwap_bias = "bullish" if current_price > intraday_vwap else "bearish"
                    
                    # Calculate intraday volume profile
                    intraday_volume_profile = self.calculate_volume_profile(intraday_data, self.intraday_volume_nodes)
                    
                    context += f"\n\nIntraday {self.intraday_interval} Volume Profile (Past {self.intraday_days} days, {len(intraday_data)} bars):"
                    context += f"\nIntraday VWAP: {intraday_vwap:.2f} | Price is {abs(intraday_vwap_diff):.2f} pts {intraday_vwap_bias.upper()}"
                    context += f"\nTop {self.intraday_volume_nodes} High Volume Zones:"
                    
                    for i, (price, volume) in enumerate(intraday_volume_profile, 1):
                        volume_pct = (volume / intraday_data['Volume'].sum()) * 100
                        context += f"\n  {i}. {price:.2f} pts ({volume_pct:.1f}% of volume)"
                        if i == 1:
                            context += " (Intraday POC)"
            
            # Add key levels
            context += f"\n\nKey Levels: Support {daily_low:.2f}, Resistance {daily_high:.2f}"
            
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

