import React, { useState, useEffect, useCallback } from 'react';
import { 
  Activity, 
  ShieldAlert, 
  CheckCircle2, 
  XCircle, 
  AlertTriangle, 
  Send, 
  RefreshCw, 
  TrendingDown, 
  TrendingUp, 
  Lock, 
  Clock, 
  DollarSign, 
  BarChart2, 
  AlertOctagon,
  Flame,
  Radio,
  Sliders,
  Layers
} from 'lucide-react';
import { apiService } from '../utils/apiService';

interface L2Level {
  price: number;
  size: number;
  orders: number;
}

interface L2Book {
  symbol: string;
  timestamp: string;
  midPrice: number;
  bids: L2Level[];
  asks: L2Level[];
  spread: number;
  spreadBps: number;
  sessionVolume: number;
  vwap: number;
  microVolatility: number;
}

export const LiveExecutionConsole: React.FC = () => {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('SPY');
  const [books, setBooks] = useState<Record<string, L2Book>>({});
  const [isStreaming, setIsStreaming] = useState<boolean>(true);
  const [lastTickUtc, setLastTickUtc] = useState<string>('');
  
  // Order submission state
  const [orderSide, setOrderSide] = useState<'BUY' | 'SELL'>('BUY');
  const [orderType, setOrderType] = useState<'LIMIT' | 'MARKET'>('LIMIT');
  const [orderQty, setOrderQty] = useState<number>(50);
  const [limitPrice, setLimitPrice] = useState<number>(562.40);
  const [isReduceOnly, setIsReduceOnly] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [submissionFeedback, setSubmissionFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Orders & Positions state
  const [orders, setOrders] = useState<any[]>([]);
  const [positions, setPositions] = useState<Record<string, any>>({});
  const [portfolio, setPortfolio] = useState<{
    cash_balance: number;
    peak_equity: number;
    total_equity: number;
    drawdown_pct: number;
  }>({
    cash_balance: 100000,
    peak_equity: 100000,
    total_equity: 100000,
    drawdown_pct: 0,
  });

  // Risk Daemon state
  const [daemonStatus, setDaemonStatus] = useState<any>(null);
  const [isTrippingBreaker, setIsTrippingBreaker] = useState<boolean>(false);
  const [isFlattening, setIsFlattening] = useState<boolean>(false);

  // Fetch orders & portfolio
  const refreshOrdersAndPortfolio = useCallback(async () => {
    try {
      const res = await apiService.getMarketOrders();
      setOrders(res.orders || []);
      setPositions(res.positions || {});
      setPortfolio({
        cash_balance: res.cash_balance,
        peak_equity: res.peak_equity,
        total_equity: res.total_equity,
        drawdown_pct: res.drawdown_pct,
      });
    } catch (e) {
      console.warn('Failed to refresh orders:', e);
    }
  }, []);

  // Fetch daemon status
  const refreshDaemonStatus = useCallback(async () => {
    try {
      const status = await apiService.getRiskDaemonStatus();
      setDaemonStatus(status);
    } catch (e) {
      console.warn('Failed to refresh daemon:', e);
    }
  }, []);

  // Poll / SSE for market stream
  useEffect(() => {
    let sse: EventSource | null = null;

    if (isStreaming && typeof window !== 'undefined' && window.EventSource) {
      try {
        sse = new EventSource('/api/market/stream');
        sse.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.books) {
              setBooks(data.books);
              setLastTickUtc(new Date().toISOString());
              // Auto-update default limit price if user hasn't edited manually
              const curBook = data.books[selectedSymbol];
              if (curBook && orderType === 'LIMIT' && limitPrice === 0) {
                setLimitPrice(orderSide === 'BUY' ? curBook.bids[0].price : curBook.asks[0].price);
              }
            }
          } catch (err) {
            console.error('SSE parse error:', err);
          }
        };
        sse.onerror = () => {
          sse?.close();
        };
      } catch {
        // Fallback to polling
      }
    }

    // Polling fallback / daemon sync interval
    const interval = setInterval(() => {
      refreshOrdersAndPortfolio();
      refreshDaemonStatus();
      if (!isStreaming || !sse) {
        apiService.getMarketSnapshot().then((res) => {
          if (res.books) {
            setBooks(res.books);
            setLastTickUtc(res.timestamp);
          }
        });
      }
    }, 1200);

    return () => {
      if (sse) sse.close();
      clearInterval(interval);
    };
  }, [isStreaming, selectedSymbol, orderSide, orderType, limitPrice, refreshOrdersAndPortfolio, refreshDaemonStatus]);

  // Sync default price on symbol change
  useEffect(() => {
    const book = books[selectedSymbol];
    if (book) {
      setLimitPrice(orderSide === 'BUY' ? book.bids[0].price : book.asks[0].price);
    }
  }, [selectedSymbol, books, orderSide]);

  const currentBook = books[selectedSymbol];

  // Calculate max sizes for depth bars
  const maxBidSize = currentBook ? Math.max(...currentBook.bids.map(b => b.size), 1000) : 3000;
  const maxAskSize = currentBook ? Math.max(...currentBook.asks.map(a => a.size), 1000) : 3000;

  // Pre-trade calculations
  const effectivePrice = orderType === 'MARKET'
    ? (currentBook ? (orderSide === 'BUY' ? currentBook.asks[0].price : currentBook.bids[0].price) : 500)
    : limitPrice;
  const orderNotional = Math.round(effectivePrice * orderQty * 100) / 100;
  const estimatedFee = Math.round(Math.max(1.0, orderQty * 0.005) * 100) / 100;
  const isBreakerActive = daemonStatus?.circuitBreakerActive ?? daemonStatus?.circuit_breaker_active;

  // Handle Order Submit
  const handleSubmitOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmissionFeedback(null);

    try {
      const res = await apiService.submitMarketOrder({
        symbol: selectedSymbol,
        side: orderSide,
        order_type: orderType,
        qty: orderQty,
        limit_price: orderType === 'LIMIT' ? limitPrice : undefined,
        is_reduce_only: isReduceOnly,
      });

      setSubmissionFeedback({
        type: 'success',
        message: `${orderSide} ${orderQty} ${selectedSymbol} [${orderType}] accepted. Order ID: ${res.order.order_id}`,
      });
      refreshOrdersAndPortfolio();
      refreshDaemonStatus();
    } catch (err: any) {
      setSubmissionFeedback({
        type: 'error',
        message: err.message || 'Order submission failed',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Emergency Flatten
  const handleEmergencyFlatten = async () => {
    if (!confirm('EMERGENCY ACTION: Cancel all resting orders and immediately close all open positions at market?')) {
      return;
    }
    setIsFlattening(true);
    try {
      const res = await apiService.emergencyFlatten();
      setSubmissionFeedback({
        type: 'success',
        message: res.message,
      });
      refreshOrdersAndPortfolio();
    } catch (err: any) {
      setSubmissionFeedback({
        type: 'error',
        message: err.message || 'Emergency flatten failed',
      });
    } finally {
      setIsFlattening(false);
    }
  };

  // Manual Kill Switch Trip
  const handleTripKillSwitch = async () => {
    if (!confirm('TRIP KILL SWITCH: Immediately trip circuit breaker and lock risk-increasing orders?')) {
      return;
    }
    setIsTrippingBreaker(true);
    try {
      await apiService.tripRiskBreaker('Manual Operator Trip via Execution Console');
      refreshDaemonStatus();
      refreshOrdersAndPortfolio();
      setSubmissionFeedback({
        type: 'error',
        message: 'Circuit breaker tripped! Risk-increasing orders locked.',
      });
    } catch (err: any) {
      console.error(err);
    } finally {
      setIsTrippingBreaker(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Console Header & Live Telemetry Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-400">
                <Radio className="w-5 h-5 animate-pulse" />
              </div>
              <h2 className="text-lg font-bold text-white tracking-tight">
                Real-Time Level-2 Execution Console &amp; Queue-Aware Order Router
              </h2>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
                Live FIX &amp; L2 Feed
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Deterministic Depth • Adverse Selection Queue Priority • Sub-millisecond Slippage Attribution • SEC 15c3-5 Pre-Trade Enforcement
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setIsStreaming(!isStreaming)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-semibold transition-colors ${
                isStreaming
                  ? 'bg-teal-500/20 text-teal-300 border border-teal-500/30'
                  : 'bg-slate-800 text-slate-400 border border-slate-700'
              }`}
            >
              <Radio className="w-3.5 h-3.5" />
              {isStreaming ? 'Stream Active (1000ms SSE)' : 'Stream Paused'}
            </button>

            <button
              onClick={handleEmergencyFlatten}
              disabled={isFlattening}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/15 hover:bg-rose-500/25 border border-rose-500/30 text-rose-300 text-xs font-bold transition-colors"
            >
              <AlertOctagon className="w-3.5 h-3.5" />
              {isFlattening ? 'Flattening...' : 'Emergency Flatten'}
            </button>

            <button
              onClick={handleTripKillSwitch}
              disabled={isTrippingBreaker || isBreakerActive}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                isBreakerActive
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 cursor-not-allowed'
                  : 'bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border border-amber-500/30'
              }`}
            >
              <Flame className="w-3.5 h-3.5 text-amber-400" />
              {isBreakerActive ? 'Breaker Tripped' : 'Trip Kill Switch'}
            </button>
          </div>
        </div>

        {/* Portfolio & Daemon Health Summary Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-4 text-xs font-mono">
          <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 block text-[10px] uppercase">Cash Balance</span>
            <span className="text-white font-semibold text-sm">
              ${portfolio.cash_balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 block text-[10px] uppercase">Mark-to-Market Equity</span>
            <span className="text-teal-400 font-semibold text-sm">
              ${portfolio.total_equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 block text-[10px] uppercase">Peak Highwater Equity</span>
            <span className="text-slate-300 font-semibold text-sm">
              ${portfolio.peak_equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 block text-[10px] uppercase">Intraday Drawdown</span>
            <span className={`font-semibold text-sm ${portfolio.drawdown_pct > 1.5 ? 'text-amber-400' : 'text-emerald-400'}`}>
              {portfolio.drawdown_pct.toFixed(2)}%
            </span>
          </div>

          <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 block text-[10px] uppercase">Daemon Guard Heartbeat</span>
            <span className="text-emerald-400 font-semibold flex items-center gap-1.5 text-xs">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              {daemonStatus?.heartbeat_ms ?? 15}ms (Checks: {daemonStatus?.checks_count ?? 0})
            </span>
          </div>

          <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 block text-[10px] uppercase">Circuit Breaker</span>
            <span className={`font-bold text-xs ${isBreakerActive ? 'text-rose-400' : 'text-emerald-400'}`}>
              {isBreakerActive ? 'TRIPPED (LOCKED)' : 'NORMAL (ALLOWED)'}
            </span>
          </div>
        </div>

        {isBreakerActive && (
          <div className="mt-3 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
              <span>
                <strong>SAFETY ALERT:</strong> {daemonStatus?.safeguards?.tripReason || 'Circuit breaker is currently active. Risk-increasing orders blocked.'}
              </span>
            </div>
            <span className="text-[10px] font-mono bg-rose-950 px-2 py-0.5 rounded border border-rose-800">
              Only REDUCE_ONLY Orders Accepted
            </span>
          </div>
        )}
      </div>

      {/* Main Trading Stage: Depth Book + Order Form */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* LEFT: Level-2 Order Book Depth Visualizer (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            {/* Symbol Switcher Tabs */}
            <div className="flex items-center justify-between pb-4 border-b border-slate-800">
              <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
                {['SPY', 'QQQ', 'TLT', 'HYG'].map((sym) => (
                  <button
                    key={sym}
                    onClick={() => setSelectedSymbol(sym)}
                    className={`px-3 py-1 rounded-md text-xs font-mono font-bold transition-colors ${
                      selectedSymbol === sym
                        ? 'bg-teal-500 text-slate-950 shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {sym}
                  </button>
                ))}
              </div>

              {currentBook && (
                <div className="flex items-center gap-4 text-xs font-mono">
                  <div>
                    <span className="text-slate-500">Mid: </span>
                    <span className="text-white font-bold text-sm">${currentBook.midPrice.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Spread: </span>
                    <span className="text-teal-400 font-semibold">${currentBook.spread.toFixed(2)} ({currentBook.spreadBps} bps)</span>
                  </div>
                  <div className="hidden sm:block">
                    <span className="text-slate-500">VWAP: </span>
                    <span className="text-slate-300">${currentBook.vwap.toFixed(2)}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Level 2 Visual Book */}
            {currentBook ? (
              <div className="mt-4 space-y-3 font-mono text-xs">
                {/* Asks (Sells) descending down to best ask */}
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-slate-500 uppercase px-2">
                    <span>Depth / Orders</span>
                    <span>Ask Size</span>
                    <span>Ask Price</span>
                  </div>
                  {currentBook.asks.slice().reverse().map((ask, idx) => {
                    const pct = Math.min(100, Math.round((ask.size / maxAskSize) * 100));
                    return (
                      <div
                        key={`ask-${ask.price}-${idx}`}
                        onClick={() => {
                          setLimitPrice(ask.price);
                          setOrderSide('BUY');
                        }}
                        className="relative flex items-center justify-between px-2 py-1 rounded bg-slate-950/60 hover:bg-rose-500/10 cursor-pointer border border-slate-800/40 transition-colors"
                      >
                        {/* Visual Depth Bar */}
                        <div
                          className="absolute right-0 top-0 bottom-0 bg-rose-500/15 rounded pointer-events-none"
                          style={{ width: `${pct}%` }}
                        />
                        <span className="relative z-10 text-slate-400 text-[11px]">
                          {ask.orders} ords
                        </span>
                        <span className="relative z-10 text-slate-300 font-medium">
                          {ask.size.toLocaleString()}
                        </span>
                        <span className="relative z-10 text-rose-400 font-bold">
                          ${ask.price.toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                </div>

                {/* Top-of-Book Spread Divider */}
                <div className="py-2 px-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400">Top-of-Book Spread:</span>
                    <span className="text-teal-300 font-bold">${currentBook.spread.toFixed(2)}</span>
                    <span className="text-slate-500 text-[11px]">({currentBook.spreadBps} bps)</span>
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Micro-Vol: <span className="text-slate-200">{(currentBook.microVolatility * 100).toFixed(1)}%</span>
                  </div>
                </div>

                {/* Bids (Buys) descending from best bid */}
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-slate-500 uppercase px-2">
                    <span>Bid Price</span>
                    <span>Bid Size</span>
                    <span>Depth / Orders</span>
                  </div>
                  {currentBook.bids.map((bid, idx) => {
                    const pct = Math.min(100, Math.round((bid.size / maxBidSize) * 100));
                    return (
                      <div
                        key={`bid-${bid.price}-${idx}`}
                        onClick={() => {
                          setLimitPrice(bid.price);
                          setOrderSide('SELL');
                        }}
                        className="relative flex items-center justify-between px-2 py-1 rounded bg-slate-950/60 hover:bg-emerald-500/10 cursor-pointer border border-slate-800/40 transition-colors"
                      >
                        {/* Visual Depth Bar */}
                        <div
                          className="absolute left-0 top-0 bottom-0 bg-emerald-500/15 rounded pointer-events-none"
                          style={{ width: `${pct}%` }}
                        />
                        <span className="relative z-10 text-emerald-400 font-bold">
                          ${bid.price.toFixed(2)}
                        </span>
                        <span className="relative z-10 text-slate-300 font-medium">
                          {bid.size.toLocaleString()}
                        </span>
                        <span className="relative z-10 text-slate-400 text-[11px]">
                          {bid.orders} ords
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="py-12 text-center text-slate-500 text-xs">
                Connecting to Level-2 simulated exchange feed...
              </div>
            )}
          </div>
        </div>

        {/* RIGHT: Order Entry & Pre-Trade Validation (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <form onSubmit={handleSubmitOrder} className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Send className="w-4 h-4 text-teal-400" />
                <span>Pre-Trade Order Entry</span>
              </h3>
              <span className="text-[11px] font-mono text-slate-400">
                SEC 15c3-5 Pre-Trade Check Active
              </span>
            </div>

            {/* Side Toggle */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setOrderSide('BUY')}
                className={`py-2 rounded-lg text-xs font-bold transition-colors ${
                  orderSide === 'BUY'
                    ? 'bg-emerald-600 text-white shadow-md'
                    : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                }`}
              >
                BUY / LONG
              </button>
              <button
                type="button"
                onClick={() => setOrderSide('SELL')}
                className={`py-2 rounded-lg text-xs font-bold transition-colors ${
                  orderSide === 'SELL'
                    ? 'bg-rose-600 text-white shadow-md'
                    : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                }`}
              >
                SELL / SHORT
              </button>
            </div>

            {/* Order Type Toggle */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setOrderType('LIMIT')}
                className={`py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                  orderType === 'LIMIT'
                    ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40'
                    : 'bg-slate-950 text-slate-400 border border-slate-800'
                }`}
              >
                LIMIT (Queue-Aware)
              </button>
              <button
                type="button"
                onClick={() => setOrderType('MARKET')}
                className={`py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                  orderType === 'MARKET'
                    ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40'
                    : 'bg-slate-950 text-slate-400 border border-slate-800'
                }`}
              >
                MARKET (Immediate Fill)
              </button>
            </div>

            {/* Quantity Selector */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Shares Quantity</span>
                <span className="font-mono">{orderQty} shares</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min="1"
                  max="2000"
                  value={orderQty}
                  onChange={(e) => setOrderQty(Math.max(1, parseInt(e.target.value) || 1))}
                  className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white font-mono text-xs focus:outline-none focus:border-teal-500"
                />
                <div className="flex items-center gap-1">
                  {[25, 50, 100, 250].map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => setOrderQty(q)}
                      className="px-2 py-1.5 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-slate-300 hover:text-white hover:border-slate-700"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Limit Price Input */}
            {orderType === 'LIMIT' && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>Limit Price ($)</span>
                  <span className="font-mono text-teal-400">${limitPrice.toFixed(2)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    step="0.01"
                    value={limitPrice}
                    onChange={(e) => setLimitPrice(parseFloat(e.target.value) || 0)}
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white font-mono text-xs focus:outline-none focus:border-teal-500"
                  />
                  <button
                    type="button"
                    onClick={() => setLimitPrice(Math.round((limitPrice - 0.01) * 100) / 100)}
                    className="px-2.5 py-2 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-slate-300 hover:text-white"
                  >
                    -0.01
                  </button>
                  <button
                    type="button"
                    onClick={() => setLimitPrice(Math.round((limitPrice + 0.01) * 100) / 100)}
                    className="px-2.5 py-2 rounded bg-slate-950 border border-slate-800 text-xs font-mono text-slate-300 hover:text-white"
                  >
                    +0.01
                  </button>
                </div>
              </div>
            )}

            {/* Reduce Only Checkbox */}
            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="reduce-only"
                checked={isReduceOnly}
                onChange={(e) => setIsReduceOnly(e.target.checked)}
                className="rounded border-slate-700 text-teal-500 focus:ring-0 focus:ring-offset-0 bg-slate-950"
              />
              <label htmlFor="reduce-only" className="text-xs text-slate-300 cursor-pointer">
                Reduce-Only Order (Mandatory if circuit breaker tripped)
              </label>
            </div>

            {/* Pre-Trade Calculation Preview */}
            <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1.5 text-xs font-mono">
              <div className="flex justify-between text-slate-400">
                <span>Est. Notional Value:</span>
                <span className="text-white font-semibold">${orderNotional.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Regulatory / Execution Fee:</span>
                <span className="text-slate-300">${estimatedFee.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Max Single-Order Barrier:</span>
                <span className="text-slate-400">$150,000.00</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Pre-Trade Safety Check:</span>
                <span className={orderNotional <= 150000 ? 'text-emerald-400' : 'text-rose-400'}>
                  {orderNotional <= 150000 ? 'PASSED (Within Bounds)' : 'BREACH (Exceeds $150k)'}
                </span>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isSubmitting || (isBreakerActive && !isReduceOnly)}
              className={`w-full py-2.5 rounded-lg text-xs font-bold transition-all shadow-md flex items-center justify-center gap-2 ${
                isBreakerActive && !isReduceOnly
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
                  : orderSide === 'BUY'
                  ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  : 'bg-rose-600 hover:bg-rose-500 text-white'
              }`}
            >
              <Send className="w-3.5 h-3.5" />
              {isSubmitting
                ? 'Routing...'
                : `Submit ${orderSide} ${orderQty} ${selectedSymbol} [${orderType}]`}
            </button>

            {/* Feedback message */}
            {submissionFeedback && (
              <div className={`p-3 rounded-lg text-xs flex items-start gap-2 ${
                submissionFeedback.type === 'success'
                  ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                  : 'bg-rose-500/10 border border-rose-500/20 text-rose-300'
              }`}>
                {submissionFeedback.type === 'success' ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                )}
                <span>{submissionFeedback.message}</span>
              </div>
            )}
          </form>
        </div>
      </div>

      {/* Real-Time Positions & Open Resting Orders */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Open Positions Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <BarChart2 className="w-4 h-4 text-teal-400" />
              <span>Mark-to-Market Positions</span>
            </h3>
            <span className="text-xs font-mono text-slate-400">
              {Object.values(positions).filter(p => p.qty !== 0).length} Active Positions
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800 text-left">
                  <th className="py-2">Symbol</th>
                  <th className="py-2">Shares</th>
                  <th className="py-2">Avg Entry</th>
                  <th className="py-2">Current Px</th>
                  <th className="py-2">Unrealized P&L</th>
                  <th className="py-2">Realized P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {Object.values(positions).map((pos: any) => (
                  <tr key={pos.symbol} className="hover:bg-slate-800/30">
                    <td className="py-2.5 font-bold text-white">{pos.symbol}</td>
                    <td className={`py-2.5 font-semibold ${pos.qty > 0 ? 'text-emerald-400' : pos.qty < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                      {pos.qty > 0 ? `+${pos.qty}` : pos.qty}
                    </td>
                    <td className="py-2.5 text-slate-300">
                      {pos.avg_price > 0 ? `$${pos.avg_price.toFixed(2)}` : '—'}
                    </td>
                    <td className="py-2.5 text-slate-300">${pos.current_price?.toFixed(2) || '—'}</td>
                    <td className={`py-2.5 font-bold ${pos.unrealized_pnl > 0 ? 'text-emerald-400' : pos.unrealized_pnl < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                      ${pos.unrealized_pnl?.toFixed(2) || '0.00'}
                    </td>
                    <td className={`py-2.5 font-bold ${pos.realized_pnl > 0 ? 'text-emerald-400' : pos.realized_pnl < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                      ${pos.realized_pnl?.toFixed(2) || '0.00'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Live Order Queue & Fill Telemetry */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Clock className="w-4 h-4 text-teal-400" />
              <span>Queue-Aware Order Telemetry</span>
            </h3>
            <span className="text-xs font-mono text-slate-400">
              {orders.filter(o => o.status === 'RESTING_IN_QUEUE').length} In Queue
            </span>
          </div>

          <div className="overflow-x-auto max-h-72 overflow-y-auto">
            {orders.length === 0 ? (
              <div className="py-10 text-center text-slate-500 text-xs font-mono">
                No orders submitted yet. Enter an order above to test queue dynamics.
              </div>
            ) : (
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-800 text-left">
                    <th className="py-2">Order ID</th>
                    <th className="py-2">Side / Sym</th>
                    <th className="py-2">Type</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Queue / Ahead</th>
                    <th className="py-2">Fill Px</th>
                    <th className="py-2">Slippage</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {orders.slice(0, 15).map((ord) => (
                    <tr key={ord.order_id} className="hover:bg-slate-800/30">
                      <td className="py-2 text-slate-400 text-[11px] truncate max-w-[90px]">{ord.order_id}</td>
                      <td className="py-2">
                        <span className={`font-bold ${ord.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {ord.side}
                        </span>{' '}
                        <span className="text-white">{ord.qty} {ord.symbol}</span>
                      </td>
                      <td className="py-2 text-slate-300">{ord.order_type}</td>
                      <td className="py-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          ord.status === 'FILLED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                          ord.status === 'RESTING_IN_QUEUE' ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 animate-pulse' :
                          ord.status === 'REJECTED' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {ord.status}
                        </span>
                      </td>
                      <td className="py-2 text-slate-300">
                        {ord.status === 'RESTING_IN_QUEUE' ? (
                          <span className="text-cyan-400 font-bold">
                            #{ord.queue_position || 1} ({ord.shares_ahead} shs)
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="py-2 text-white font-semibold">
                        {ord.avg_fill_price ? `$${ord.avg_fill_price.toFixed(2)}` : '—'}
                      </td>
                      <td className="py-2 text-slate-400">
                        {ord.slippage_bps !== undefined ? `${ord.slippage_bps} bps` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
