export interface MarketSessionBar {
  day_number: number;
  session_date: string;
  spy_close: number;
  qqq_close: number;
  volatility_regime: 'LOW' | 'NORMAL' | 'ELEVATED';
  model_signal: 'BUY' | 'SELL' | 'HOLD';
  target_symbol: 'SPY' | 'QQQ';
  recommended_shares: number;
  model_confidence: number;
  news_sentiment: 'NEGATIVE' | 'NEUTRAL' | 'POSITIVE';
}

// Deterministic simulated market bars for exercising the paper-broker UI.
// They are fixtures, not historical market data or live execution evidence.
const session = (
  day_number: number,
  session_date: string,
  spy_close: number,
  qqq_close: number,
  volatility_regime: MarketSessionBar['volatility_regime'],
  model_signal: MarketSessionBar['model_signal'],
  target_symbol: MarketSessionBar['target_symbol'],
  recommended_shares: number,
  model_confidence: number,
  news_sentiment: MarketSessionBar['news_sentiment'],
): MarketSessionBar => ({
  day_number, session_date, spy_close, qqq_close, volatility_regime,
  model_signal, target_symbol, recommended_shares, model_confidence, news_sentiment,
});

export const PAPER_MARKET_SESSIONS: MarketSessionBar[] = [
  session(1, '2026-09-01', 580.12, 503.48, 'NORMAL', 'HOLD', 'SPY', 0, 0.51, 'NEUTRAL'),
  session(2, '2026-09-02', 582.35, 506.21, 'NORMAL', 'BUY', 'SPY', 20, 0.68, 'POSITIVE'),
  session(3, '2026-09-03', 581.44, 505.67, 'NORMAL', 'HOLD', 'SPY', 0, 0.54, 'NEUTRAL'),
  session(4, '2026-09-04', 584.18, 508.32, 'LOW', 'BUY', 'QQQ', 15, 0.65, 'POSITIVE'),
  session(5, '2026-09-08', 582.76, 506.85, 'NORMAL', 'HOLD', 'QQQ', 0, 0.5, 'NEUTRAL'),
  session(6, '2026-09-09', 585.63, 510.14, 'LOW', 'SELL', 'SPY', 10, 0.62, 'NEGATIVE'),
  session(7, '2026-09-10', 583.95, 508.91, 'NORMAL', 'HOLD', 'SPY', 0, 0.53, 'NEUTRAL'),
  session(8, '2026-09-11', 579.84, 504.76, 'ELEVATED', 'SELL', 'QQQ', 8, 0.64, 'NEGATIVE'),
  session(9, '2026-09-14', 581.27, 506.03, 'NORMAL', 'HOLD', 'QQQ', 0, 0.52, 'NEUTRAL'),
  session(10, '2026-09-15', 586.02, 511.48, 'LOW', 'BUY', 'SPY', 12, 0.67, 'POSITIVE'),
  session(11, '2026-09-16', 587.41, 513.2, 'LOW', 'HOLD', 'SPY', 0, 0.51, 'NEUTRAL'),
  session(12, '2026-09-17', 584.67, 509.62, 'NORMAL', 'SELL', 'SPY', 10, 0.61, 'NEGATIVE'),
  session(13, '2026-09-18', 586.28, 511.07, 'NORMAL', 'HOLD', 'SPY', 0, 0.5, 'NEUTRAL'),
  session(14, '2026-09-21', 588.14, 514.51, 'LOW', 'BUY', 'QQQ', 10, 0.66, 'POSITIVE'),
  session(15, '2026-09-22', 589.03, 515.8, 'LOW', 'HOLD', 'QQQ', 0, 0.52, 'NEUTRAL'),
  session(16, '2026-09-23', 585.77, 511.43, 'ELEVATED', 'SELL', 'QQQ', 7, 0.63, 'NEGATIVE'),
  session(17, '2026-09-24', 587.36, 513.72, 'NORMAL', 'HOLD', 'SPY', 0, 0.51, 'NEUTRAL'),
  session(18, '2026-09-25', 590.25, 516.94, 'LOW', 'BUY', 'SPY', 10, 0.69, 'POSITIVE'),
  session(19, '2026-09-28', 591.18, 518.22, 'LOW', 'HOLD', 'SPY', 0, 0.53, 'NEUTRAL'),
  session(20, '2026-09-29', 588.92, 515.16, 'NORMAL', 'SELL', 'SPY', 10, 0.6, 'NEGATIVE'),
];
