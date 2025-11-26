-- Create view for daily trading statistics
CREATE OR REPLACE VIEW daily_trade_stats AS
SELECT 
    DATE(timestamp) as trade_date,
    account_id,
    symbol,
    COUNT(DISTINCT order_id) as total_trades,
    COUNT(CASE WHEN event_type = 'ENTRY' THEN 1 END) as entries,
    COUNT(CASE WHEN event_type = 'CLOSE' THEN 1 END) as closes,
    COUNT(CASE WHEN position_type = 'long' THEN 1 END) as long_trades,
    COUNT(CASE WHEN position_type = 'short' THEN 1 END) as short_trades,
    SUM(CASE WHEN event_type = 'CLOSE' THEN profit_loss END) as total_pnl,
    SUM(CASE WHEN event_type = 'CLOSE' THEN profit_loss_points END) as total_points,
    AVG(CASE WHEN event_type = 'CLOSE' THEN profit_loss END) as avg_pnl_per_trade,
    COUNT(CASE WHEN event_type = 'CLOSE' AND profit_loss > 0 THEN 1 END) as winning_trades,
    COUNT(CASE WHEN event_type = 'CLOSE' AND profit_loss < 0 THEN 1 END) as losing_trades,
    MAX(CASE WHEN event_type = 'CLOSE' THEN profit_loss END) as largest_win,
    MIN(CASE WHEN event_type = 'CLOSE' THEN profit_loss END) as largest_loss,
    MAX(balance) as end_of_day_balance
FROM trades
GROUP BY DATE(timestamp), account_id, symbol
ORDER BY trade_date DESC;

-- Create view for win rate analysis
CREATE OR REPLACE VIEW win_rate_analysis AS
SELECT 
    account_id,
    symbol,
    position_type,
    COUNT(DISTINCT order_id) as total_closed_trades,
    COUNT(CASE WHEN profit_loss > 0 THEN 1 END) as wins,
    COUNT(CASE WHEN profit_loss < 0 THEN 1 END) as losses,
    ROUND(
        CAST(COUNT(CASE WHEN profit_loss > 0 THEN 1 END) AS NUMERIC) / 
        NULLIF(COUNT(DISTINCT order_id), 0) * 100, 
        2
    ) as win_rate_pct,
    SUM(profit_loss) as total_pnl,
    AVG(profit_loss) as avg_pnl,
    AVG(CASE WHEN profit_loss > 0 THEN profit_loss END) as avg_win,
    AVG(CASE WHEN profit_loss < 0 THEN profit_loss END) as avg_loss,
    AVG(CASE WHEN profit_loss > 0 THEN profit_loss END) / 
    NULLIF(ABS(AVG(CASE WHEN profit_loss < 0 THEN profit_loss END)), 0) as profit_factor
FROM trades
WHERE event_type = 'CLOSE' AND profit_loss IS NOT NULL
GROUP BY account_id, symbol, position_type;

-- Create view for monthly performance summary
CREATE OR REPLACE VIEW monthly_performance AS
SELECT 
    DATE_TRUNC('month', timestamp) as month,
    account_id,
    symbol,
    COUNT(DISTINCT order_id) as total_trades,
    SUM(CASE WHEN event_type = 'CLOSE' THEN profit_loss END) as monthly_pnl,
    SUM(CASE WHEN event_type = 'CLOSE' THEN profit_loss_points END) as monthly_points,
    COUNT(CASE WHEN event_type = 'CLOSE' AND profit_loss > 0 THEN 1 END) as winning_trades,
    COUNT(CASE WHEN event_type = 'CLOSE' AND profit_loss < 0 THEN 1 END) as losing_trades,
    MAX(balance) as ending_balance,
    MIN(balance) as lowest_balance,
    MAX(balance) - MIN(balance) as drawdown
FROM trades
GROUP BY DATE_TRUNC('month', timestamp), account_id, symbol
ORDER BY month DESC;

-- Create view for recent trade activity
CREATE OR REPLACE VIEW recent_trades AS
SELECT 
    t.id,
    t.account_id,
    t.order_id,
    t.timestamp,
    t.event_type,
    t.symbol,
    t.position_type,
    t.size,
    t.price,
    t.entry_price,
    t.stop_loss,
    t.take_profit,
    t.profit_loss,
    t.profit_loss_points,
    t.balance,
    t.reasoning,
    t.confidence
FROM trades t
ORDER BY t.timestamp DESC
LIMIT 100;

COMMENT ON VIEW daily_trade_stats IS 'Daily aggregated trading statistics by account and symbol';
COMMENT ON VIEW win_rate_analysis IS 'Win rate and profitability metrics by account, symbol, and position type';
COMMENT ON VIEW monthly_performance IS 'Monthly performance summary with P&L and drawdown';
COMMENT ON VIEW recent_trades IS 'Most recent 100 trades for quick reference';

