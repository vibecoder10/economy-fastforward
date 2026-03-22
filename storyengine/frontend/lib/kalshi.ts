import crypto from "crypto";
import type {
  KalshiMarketsResponse,
  KalshiEventsResponse,
  KalshiMarket,
  KalshiOrderbook,
  KalshiBalance,
  KalshiPositionsResponse,
  KalshiOrdersResponse,
  KalshiOrder,
  KalshiFillsResponse,
  KalshiPlaceOrderParams,
} from "./kalshi-types";

const KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2";
const KALSHI_DEMO_URL = "https://demo-api.kalshi.co/trade-api/v2";

export class KalshiClient {
  private baseUrl: string;
  private apiKeyId: string | null;
  private privateKey: string | null;

  constructor(opts?: {
    apiKeyId?: string;
    privateKey?: string;
    demo?: boolean;
  }) {
    this.baseUrl = opts?.demo ? KALSHI_DEMO_URL : KALSHI_BASE_URL;
    this.apiKeyId = opts?.apiKeyId ?? null;
    this.privateKey = opts?.privateKey ?? null;
  }

  private signRequest(
    method: string,
    path: string,
    timestampMs: number
  ): string {
    if (!this.privateKey) throw new Error("Private key not configured");

    const message = `${timestampMs}\n${method.toUpperCase()}\n${path}`;
    const signature = crypto.sign("sha256", Buffer.from(message), {
      key: this.privateKey,
      padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
      saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
    });
    return signature.toString("base64");
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    authenticated = false
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };

    if (authenticated) {
      if (!this.apiKeyId || !this.privateKey) {
        throw new Error("Kalshi credentials not configured");
      }
      const timestamp = Date.now();
      headers["KALSHI-ACCESS-KEY"] = this.apiKeyId;
      headers["KALSHI-ACCESS-TIMESTAMP"] = String(timestamp);
      headers["KALSHI-ACCESS-SIGNATURE"] = this.signRequest(
        method,
        path,
        timestamp
      );
    }

    const res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Kalshi API ${res.status}: ${text}`);
    }

    return res.json();
  }

  // === Public endpoints (no auth) ===

  async getMarkets(params?: {
    cursor?: string;
    limit?: number;
    event_ticker?: string;
    status?: string;
    series_ticker?: string;
  }): Promise<KalshiMarketsResponse> {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set("cursor", params.cursor);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.event_ticker) qs.set("event_ticker", params.event_ticker);
    if (params?.status) qs.set("status", params.status);
    if (params?.series_ticker) qs.set("series_ticker", params.series_ticker);
    const query = qs.toString();
    return this.request("GET", `/markets${query ? `?${query}` : ""}`);
  }

  async getMarket(ticker: string): Promise<{ market: KalshiMarket }> {
    return this.request("GET", `/markets/${ticker}`);
  }

  async getOrderbook(ticker: string): Promise<{ orderbook: KalshiOrderbook }> {
    return this.request("GET", `/markets/${ticker}/orderbook`);
  }

  async getEvents(params?: {
    cursor?: string;
    limit?: number;
    status?: string;
    with_nested_markets?: boolean;
  }): Promise<KalshiEventsResponse> {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set("cursor", params.cursor);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.status) qs.set("status", params.status);
    if (params?.with_nested_markets)
      qs.set("with_nested_markets", "true");
    const query = qs.toString();
    return this.request("GET", `/events${query ? `?${query}` : ""}`);
  }

  // === Authenticated endpoints ===

  async getBalance(): Promise<KalshiBalance> {
    return this.request("GET", "/portfolio/balance", undefined, true);
  }

  async getPositions(params?: {
    cursor?: string;
    limit?: number;
    settlement_status?: string;
  }): Promise<KalshiPositionsResponse> {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set("cursor", params.cursor);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.settlement_status)
      qs.set("settlement_status", params.settlement_status);
    const query = qs.toString();
    return this.request(
      "GET",
      `/portfolio/positions${query ? `?${query}` : ""}`,
      undefined,
      true
    );
  }

  async placeOrder(params: KalshiPlaceOrderParams): Promise<{ order: KalshiOrder }> {
    return this.request("POST", "/portfolio/orders", params, true);
  }

  async getOrders(params?: {
    cursor?: string;
    limit?: number;
    ticker?: string;
    status?: string;
  }): Promise<KalshiOrdersResponse> {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set("cursor", params.cursor);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.ticker) qs.set("ticker", params.ticker);
    if (params?.status) qs.set("status", params.status);
    const query = qs.toString();
    return this.request(
      "GET",
      `/portfolio/orders${query ? `?${query}` : ""}`,
      undefined,
      true
    );
  }

  async cancelOrder(orderId: string): Promise<{ order: KalshiOrder }> {
    return this.request(
      "DELETE",
      `/portfolio/orders/${orderId}`,
      undefined,
      true
    );
  }

  async getFills(params?: {
    cursor?: string;
    limit?: number;
    ticker?: string;
  }): Promise<KalshiFillsResponse> {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set("cursor", params.cursor);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.ticker) qs.set("ticker", params.ticker);
    const query = qs.toString();
    return this.request(
      "GET",
      `/portfolio/fills${query ? `?${query}` : ""}`,
      undefined,
      true
    );
  }
}
