// Kalshi API v2 TypeScript interfaces

export interface KalshiEvent {
  event_ticker: string;
  title: string;
  category: string;
  sub_title?: string;
  mutually_exclusive: boolean;
  markets: KalshiMarket[];
}

export interface KalshiMarket {
  ticker: string;
  event_ticker: string;
  title: string;
  subtitle?: string;
  status: "open" | "closed" | "settled";
  yes_bid: number; // cents (0-99)
  yes_ask: number;
  no_bid: number;
  no_ask: number;
  last_price: number;
  volume: number;
  volume_24h: number;
  open_interest: number;
  close_time: string; // ISO date
  result?: "yes" | "no" | "all_no" | "all_yes";
  category: string;
  yes_sub_title?: string;
  no_sub_title?: string;
}

export interface KalshiOrderbook {
  yes: KalshiOrderbookLevel[];
  no: KalshiOrderbookLevel[];
}

export interface KalshiOrderbookLevel {
  price: number; // cents
  quantity: number;
}

export interface KalshiOrder {
  order_id: string;
  ticker: string;
  status: "resting" | "canceled" | "executed" | "pending";
  side: "yes" | "no";
  action: "buy" | "sell";
  type: "limit" | "market";
  yes_price: number;
  no_price: number;
  contracts: number;
  remaining_count: number;
  created_time: string;
}

export interface KalshiPosition {
  ticker: string;
  event_ticker: string;
  market_exposure: number; // cents
  realized_pnl: number;
  resting_orders_count: number;
  total_traded: number;
  position: number; // positive = yes, negative = no
}

export interface KalshiBalance {
  balance: number; // cents
  portfolio_value: number; // cents
}

export interface KalshiFill {
  trade_id: string;
  ticker: string;
  side: "yes" | "no";
  action: "buy" | "sell";
  count: number;
  yes_price: number;
  no_price: number;
  created_time: string;
}

// API response wrappers
export interface KalshiMarketsResponse {
  markets: KalshiMarket[];
  cursor?: string;
}

export interface KalshiEventsResponse {
  events: KalshiEvent[];
  cursor?: string;
}

export interface KalshiOrdersResponse {
  orders: KalshiOrder[];
  cursor?: string;
}

export interface KalshiPositionsResponse {
  market_positions: KalshiPosition[];
  cursor?: string;
}

export interface KalshiFillsResponse {
  fills: KalshiFill[];
  cursor?: string;
}

export interface KalshiPlaceOrderParams {
  ticker: string;
  side: "yes" | "no";
  action: "buy" | "sell";
  type: "limit" | "market";
  count: number; // number of contracts
  yes_price?: number; // cents, required for limit orders
  no_price?: number;
}
