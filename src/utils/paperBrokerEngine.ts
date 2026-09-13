// Pure TypeScript SHA-256 and Paper Broker State Engine
// Faithfully models src/quant_research/execution/paper.py and paper_validation.py

import { 
  PaperOrder, 
  PaperPosition, 
  PaperAuditEvent, 
  PaperValidationReport, 
  PromotionState 
} from '../types';

// Fast synchronous SHA-256 implementation for immutable audit chaining
function sha256(ascii: string): string {
  function rightRotate(value: number, amount: number) {
    return (value >>> amount) | (value << (32 - amount));
  }

  const mathPow = Math.pow;
  const maxWord = mathPow(2, 32);
  let lengthProperty = 'length';
  let i: number, j: number;
  let result = '';

  const words: number[] = [];
  const asciiBitLength = ascii.length * 8;

  let hash = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
  ];

  const k = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  let compositeHash: any = hash.slice(0);
  words[asciiBitLength >> 5] |= 0x80 << (24 - asciiBitLength % 32);
  words[(((asciiBitLength + 64) >> 9) << 4) + 15] = asciiBitLength;

  for (i = 0; i < words.length; i += 16) {
    const w = words.slice(i, i + 16);
    const oldHash = compositeHash;
    compositeHash = compositeHash.slice(0, 8);

    for (j = 0; j < 64; j++) {
      const i2 = j + i;
      const w15 = w[j - 15], w2 = w[j - 2];

      const a = compositeHash[0], e = compositeHash[4];
      const s1 = rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25);
      const ch = (e & compositeHash[5]) ^ ((~e) & compositeHash[6]);
      const temp1 = compositeHash[7] + s1 + ch + k[j] + (w[j] = (j < 16) ? w[j] : (
        w[j - 16] +
        (rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3)) +
        w[j - 7] +
        (rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10))
      ) | 0);
      const s0 = rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22);
      const maj = (a & compositeHash[1]) ^ (a & compositeHash[2]) ^ (compositeHash[1] & compositeHash[2]);
      const temp2 = s0 + maj;

      compositeHash = [(temp1 + temp2) | 0].concat(compositeHash);
      compositeHash[4] = (compositeHash[4] + temp1) | 0;
    }

    for (j = 0; j < 8; j++) {
      compositeHash[j] = (compositeHash[j] + oldHash[j]) | 0;
    }
  }

  for (i = 0; i < 8; i++) {
    for (j = 3; j >= 0; j--) {
      const b = (compositeHash[i] >> (8 * j)) & 255;
      result += ((b < 16) ? 0 : '') + b.toString(16);
    }
  }
  return result;
}

export { sha256 };

export interface BrokerState {
  cash: number;
  initialCash: number;
  positions: Record<string, PaperPosition>;
  orders: PaperOrder[];
  auditTrail: PaperAuditEvent[];
  killSwitchActive: boolean;
  killSwitchTested: boolean;
  killSwitchReset: boolean;
  safeguardBreaches: number;
  reconciliationFailures: number;
  peakPortfolioValue: number;
  maxDrawdownObserved: number;
  observedSessions: string[];
  lastBarTimestamp: string | null;
}

export interface SafeguardsConfig {
  maxPositionShares: number; // e.g., 500 shares max
  maxDailyLossPct: number;    // e.g., 0.02 (2% max loss per day)
  maxPortfolioDrawdownPct: number; // e.g., 0.20 (20% max DD)
  maxDataAgeBars: number;     // e.g., 3 bars max
}

export const DEFAULT_SAFEGUARDS: SafeguardsConfig = {
  maxPositionShares: 500,
  maxDailyLossPct: 0.02,
  maxPortfolioDrawdownPct: 0.20,
  maxDataAgeBars: 3,
};

export function createInitialBrokerState(initialCash = 100000): BrokerState {
  const genesisHash = sha256(`GENESIS_${new Date().toISOString()}_INITIAL_CASH_${initialCash}`);
  const genesisEvent: PaperAuditEvent = {
    id: 'evt_genesis_000',
    timestamp: new Date().toISOString(),
    event_type: 'RECONCILIATION_RUN',
    detail: `Broker initialized with $${initialCash.toLocaleString()} cash. Position ledger zeroed.`,
    previous_hash: '0000000000000000000000000000000000000000000000000000000000000000',
    event_hash: genesisHash
  };

  return {
    cash: initialCash,
    initialCash,
    positions: {},
    orders: [],
    auditTrail: [genesisEvent],
    killSwitchActive: false,
    killSwitchTested: false,
    killSwitchReset: false,
    safeguardBreaches: 0,
    reconciliationFailures: 0,
    peakPortfolioValue: initialCash,
    maxDrawdownObserved: 0,
    observedSessions: [],
    lastBarTimestamp: null
  };
}

export function appendAuditEvent(
  trail: PaperAuditEvent[], 
  eventType: PaperAuditEvent['event_type'], 
  detail: string, 
  orderId?: string, 
  symbol?: string
): PaperAuditEvent[] {
  const prevEvent = trail[trail.length - 1];
  const prevHash = prevEvent ? prevEvent.event_hash : '0000000000000000000000000000000000000000000000000000000000000000';
  const timestamp = new Date().toISOString();
  const rawPayload = `${prevHash}|${timestamp}|${eventType}|${orderId || ''}|${symbol || ''}|${detail}`;
  const eventHash = sha256(rawPayload);

  const newEvent: PaperAuditEvent = {
    id: `evt_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
    timestamp,
    event_type: eventType,
    order_id: orderId,
    symbol,
    detail,
    previous_hash: prevHash,
    event_hash: eventHash
  };

  return [...trail, newEvent];
}

export function calculatePortfolioValue(
  cash: number, 
  positions: Record<string, PaperPosition>, 
  marketPrices: Record<string, number>
): number {
  let posValue = 0;
  for (const sym of Object.keys(positions)) {
    const pos = positions[sym];
    const price = marketPrices[sym] ?? pos.current_price;
    posValue += pos.quantity * price;
  }
  return cash + posValue;
}

export function checkSafeguards(
  order: { symbol: string; side: 'BUY' | 'SELL'; quantity: number },
  currentPosition: number,
  portfolioValue: number,
  peakValue: number,
  killSwitchActive: boolean,
  safeguards: SafeguardsConfig
): { passed: boolean; reason?: string } {
  if (killSwitchActive) {
    return { passed: false, reason: 'EMERGENCY_KILL_SWITCH_ACTIVE: all trading halted' };
  }

  const newQty = order.side === 'BUY' ? currentPosition + order.quantity : currentPosition - order.quantity;
  if (Math.abs(newQty) > safeguards.maxPositionShares) {
    return { 
      passed: false, 
      reason: `POSITION_LIMIT_EXCEEDED: Resulting position |${newQty}| exceeds max limit of ${safeguards.maxPositionShares} shares` 
    };
  }

  if (peakValue > 0) {
    const currentDrawdown = (portfolioValue - peakValue) / peakValue;
    if (currentDrawdown < -safeguards.maxPortfolioDrawdownPct) {
      return { 
        passed: false, 
        reason: `PORTFOLIO_DRAWDOWN_EXCEEDED: Drawdown ${(currentDrawdown * 100).toFixed(2)}% breached max limit of ${safeguards.maxPortfolioDrawdownPct * 100}%` 
      };
    }
  }

  return { passed: true };
}

export function submitPaperOrder(
  state: BrokerState,
  orderInput: {
    symbol: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    orderType: 'MARKET' | 'LIMIT';
    limitPrice?: number;
    expectedPrice: number;
    feeBps?: number;
    slippageBps?: number;
  },
  safeguards: SafeguardsConfig = DEFAULT_SAFEGUARDS
): { newState: BrokerState; order: PaperOrder } {
  const feeBps = orderInput.feeBps ?? 2.0;
  const slippageBps = orderInput.slippageBps ?? 1.5;
  const currentPos = state.positions[orderInput.symbol]?.quantity ?? 0;
  const portfolioVal = calculatePortfolioValue(state.cash, state.positions, { [orderInput.symbol]: orderInput.expectedPrice });

  const safeguardCheck = checkSafeguards(
    orderInput, 
    currentPos, 
    portfolioVal, 
    state.peakPortfolioValue, 
    state.killSwitchActive, 
    safeguards
  );

  const orderId = `ord_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;
  const nowStr = new Date().toISOString();

  if (!safeguardCheck.passed) {
    const rejectedOrder: PaperOrder = {
      order_id: orderId,
      symbol: orderInput.symbol,
      side: orderInput.side,
      quantity: orderInput.quantity,
      order_type: orderInput.orderType,
      limit_price: orderInput.limitPrice,
      status: 'REJECTED',
      filled_quantity: 0,
      remaining_quantity: orderInput.quantity,
      expected_price: orderInput.expectedPrice,
      slippage_bps: slippageBps,
      fee_paid: 0,
      created_at: nowStr,
      submitted_at: nowStr,
      rejected_at: nowStr,
      cancel_reason: safeguardCheck.reason,
      latency_bars: 1
    };

    let newBreaches = state.safeguardBreaches;
    if (!state.killSwitchActive) {
      newBreaches += 1;
    }

    const newTrail = appendAuditEvent(
      state.auditTrail,
      'ORDER_REJECTED',
      `Order ${orderId} for ${orderInput.side} ${orderInput.quantity} ${orderInput.symbol} REJECTED: ${safeguardCheck.reason}`,
      orderId,
      orderInput.symbol
    );

    return {
      newState: {
        ...state,
        orders: [rejectedOrder, ...state.orders],
        auditTrail: newTrail,
        safeguardBreaches: newBreaches
      },
      order: rejectedOrder
    };
  }

  // Calculate realistic execution price with slippage
  // For BUY: execution is expectedPrice * (1 + slippageBps / 10000)
  // For SELL: execution is expectedPrice * (1 - slippageBps / 10000)
  const slippageMultiplier = orderInput.side === 'BUY' 
    ? (1 + slippageBps / 10000) 
    : (1 - slippageBps / 10000);
  const fillPrice = Math.round(orderInput.expectedPrice * slippageMultiplier * 100) / 100;

  // Check limit order constraints if applicable
  if (orderInput.orderType === 'LIMIT' && orderInput.limitPrice !== undefined) {
    if (orderInput.side === 'BUY' && fillPrice > orderInput.limitPrice) {
      // Pending limit order
      const pendingOrder: PaperOrder = {
        order_id: orderId,
        symbol: orderInput.symbol,
        side: orderInput.side,
        quantity: orderInput.quantity,
        order_type: orderInput.orderType,
        limit_price: orderInput.limitPrice,
        status: 'SUBMITTED',
        filled_quantity: 0,
        remaining_quantity: orderInput.quantity,
        expected_price: orderInput.expectedPrice,
        slippage_bps: slippageBps,
        fee_paid: 0,
        created_at: nowStr,
        submitted_at: nowStr,
        latency_bars: 1
      };
      const newTrail = appendAuditEvent(
        state.auditTrail,
        'ORDER_SUBMITTED',
        `Limit Order ${orderId} submitted for ${orderInput.side} ${orderInput.quantity} ${orderInput.symbol} @ limit $${orderInput.limitPrice}`,
        orderId,
        orderInput.symbol
      );
      return {
        newState: {
          ...state,
          orders: [pendingOrder, ...state.orders],
          auditTrail: newTrail
        },
        order: pendingOrder
      };
    }
  }

  // Execute Fill
  const notional = fillPrice * orderInput.quantity;
  const feePaid = Math.round((notional * (feeBps / 10000)) * 100) / 100;

  // Cash accounting:
  // BUY: cash decreases by notional + fee
  // SELL: cash increases by notional - fee
  const cashDelta = orderInput.side === 'BUY' ? -(notional + feePaid) : (notional - feePaid);
  const newCash = Math.round((state.cash + cashDelta) * 100) / 100;

  // Position accounting
  const existingPos = state.positions[orderInput.symbol] || {
    symbol: orderInput.symbol,
    quantity: 0,
    avg_entry_price: 0,
    current_price: fillPrice,
    realized_pnl: 0,
    unrealized_pnl: 0
  };

  let newPositionQty = existingPos.quantity;
  let newAvgEntry = existingPos.avg_entry_price;
  let addedRealizedPnl = 0;

  if (orderInput.side === 'BUY') {
    if (existingPos.quantity >= 0) {
      const totalCost = (existingPos.quantity * existingPos.avg_entry_price) + (orderInput.quantity * fillPrice);
      newPositionQty = existingPos.quantity + orderInput.quantity;
      newAvgEntry = newPositionQty > 0 ? totalCost / newPositionQty : 0;
    } else {
      // Covering short position
      const coverQty = Math.min(Math.abs(existingPos.quantity), orderInput.quantity);
      addedRealizedPnl += (existingPos.avg_entry_price - fillPrice) * coverQty;
      newPositionQty = existingPos.quantity + orderInput.quantity;
      if (newPositionQty > 0) {
        newAvgEntry = fillPrice;
      }
    }
  } else {
    // SELL
    if (existingPos.quantity <= 0) {
      const totalShortVal = (Math.abs(existingPos.quantity) * existingPos.avg_entry_price) + (orderInput.quantity * fillPrice);
      newPositionQty = existingPos.quantity - orderInput.quantity;
      newAvgEntry = Math.abs(newPositionQty) > 0 ? totalShortVal / Math.abs(newPositionQty) : 0;
    } else {
      // Selling long position
      const sellQty = Math.min(existingPos.quantity, orderInput.quantity);
      addedRealizedPnl += (fillPrice - existingPos.avg_entry_price) * sellQty;
      newPositionQty = existingPos.quantity - orderInput.quantity;
      if (newPositionQty < 0) {
        newAvgEntry = fillPrice;
      }
    }
  }

  const updatedPositions = { ...state.positions };
  if (Math.abs(newPositionQty) < 1e-6) {
    delete updatedPositions[orderInput.symbol];
  } else {
    updatedPositions[orderInput.symbol] = {
      symbol: orderInput.symbol,
      quantity: newPositionQty,
      avg_entry_price: Math.round(newAvgEntry * 100) / 100,
      current_price: fillPrice,
      realized_pnl: Math.round((existingPos.realized_pnl + addedRealizedPnl) * 100) / 100,
      unrealized_pnl: Math.round(((fillPrice - newAvgEntry) * newPositionQty) * 100) / 100
    };
  }

  const filledOrder: PaperOrder = {
    order_id: orderId,
    symbol: orderInput.symbol,
    side: orderInput.side,
    quantity: orderInput.quantity,
    order_type: orderInput.orderType,
    limit_price: orderInput.limitPrice,
    status: 'FILLED',
    filled_quantity: orderInput.quantity,
    filled_price: fillPrice,
    remaining_quantity: 0,
    expected_price: orderInput.expectedPrice,
    slippage_bps: slippageBps,
    fee_paid: feePaid,
    created_at: nowStr,
    submitted_at: nowStr,
    filled_at: nowStr,
    latency_bars: 1
  };

  const currentEquity = calculatePortfolioValue(newCash, updatedPositions, { [orderInput.symbol]: fillPrice });
  const newPeak = Math.max(state.peakPortfolioValue, currentEquity);
  const drawdown = newPeak > 0 ? (currentEquity - newPeak) / newPeak : 0;
  const worstDd = Math.min(state.maxDrawdownObserved, drawdown);

  let newTrail = appendAuditEvent(
    state.auditTrail,
    'ORDER_FILLED',
    `FILLED ${orderInput.side} ${orderInput.quantity} ${orderInput.symbol} @ $${fillPrice.toFixed(2)} (Slippage: ${slippageBps} bps, Fee: $${feePaid.toFixed(2)})`,
    orderId,
    orderInput.symbol
  );

  return {
    newState: {
      ...state,
      cash: newCash,
      positions: updatedPositions,
      orders: [filledOrder, ...state.orders],
      auditTrail: newTrail,
      peakPortfolioValue: newPeak,
      maxDrawdownObserved: worstDd
    },
    order: filledOrder
  };
}

export function reconcileLedger(state: BrokerState, marketPrices: Record<string, number>): {
  consistent: boolean;
  totalRealized: number;
  totalUnrealized: number;
  totalFeesPaid: number;
  reconciliationDiscrepancy: number;
  positionSummary: Array<{ symbol: string; qty: number; value: number }>;
} {
  let realizedPnl = 0;
  let unrealizedPnl = 0;
  let totalFees = 0;

  for (const o of state.orders) {
    if (o.status === 'FILLED') {
      totalFees += o.fee_paid;
    }
  }

  const posSummary = [];
  for (const sym of Object.keys(state.positions)) {
    const pos = state.positions[sym];
    const px = marketPrices[sym] ?? pos.current_price;
    realizedPnl += pos.realized_pnl;
    const unPnl = (px - pos.avg_entry_price) * pos.quantity;
    unrealizedPnl += unPnl;
    posSummary.push({
      symbol: sym,
      qty: pos.quantity,
      value: pos.quantity * px
    });
  }

  const currentEquity = state.cash + posSummary.reduce((acc, p) => acc + p.value, 0);
  const theoreticalEquity = state.initialCash + realizedPnl + unrealizedPnl - totalFees;
  const discrepancy = Math.abs(currentEquity - theoreticalEquity);
  const consistent = discrepancy < 0.05; // sub-cent tolerance due to float rounding

  return {
    consistent,
    totalRealized: Math.round(realizedPnl * 100) / 100,
    totalUnrealized: Math.round(unrealizedPnl * 100) / 100,
    totalFeesPaid: Math.round(totalFees * 100) / 100,
    reconciliationDiscrepancy: Math.round(discrepancy * 10000) / 10000,
    positionSummary: posSummary
  };
}

export function evaluatePaperGates(
  report: PaperValidationReport,
  minDaysValidated = 5,
  minDaysLiveEligible = 60
): {
  gateResults: Record<string, boolean>;
  recommendation: 'REMAIN_PAPER_READY' | 'PAPER_VALIDATED' | 'LIVE_ELIGIBLE' | 'REJECT';
  allPassed: boolean;
} {
  const gates: Record<string, boolean> = {
    research_binding: !!report.experiment_id && report.state !== 'RESEARCH_ONLY',
    observed_session_evidence: report.observed_sessions.length > 0 && report.n_days_executed >= report.observed_sessions.length,
    min_execution_days: report.n_days_executed >= minDaysValidated,
    no_safeguard_breaches: report.n_safeguard_breaches === 0,
    reconciliation_consistent: report.final_reconciliation_consistent && report.n_reconciliation_failures === 0,
    kill_switch_tested: report.kill_switch_tested && report.kill_switch_reset,
    daily_loss_controlled: report.max_drawdown_observed >= -0.02
  };

  const allPassed = Object.values(gates).every(Boolean);

  let recommendation: 'REMAIN_PAPER_READY' | 'PAPER_VALIDATED' | 'LIVE_ELIGIBLE' | 'REJECT';
  if (allPassed && report.n_days_executed >= minDaysLiveEligible) {
    recommendation = 'LIVE_ELIGIBLE';
  } else if (allPassed && report.n_days_executed >= minDaysValidated) {
    recommendation = 'PAPER_VALIDATED';
  } else if (!gates.research_binding || !gates.no_safeguard_breaches) {
    recommendation = 'REJECT';
  } else {
    recommendation = 'REMAIN_PAPER_READY';
  }

  return {
    gateResults: gates,
    recommendation,
    allPassed
  };
}
