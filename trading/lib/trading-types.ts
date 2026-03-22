// Frontend display types for the trading UI

export interface MarketDisplayData {
  ticker: string;
  eventTicker: string;
  title: string;
  yesPrice: number; // cents (0-99)
  noPrice: number;
  volume: number;
  volume24h: number;
  closeTime: string;
  category: string;
  status: "open" | "closed" | "settled";
  isWatchlisted?: boolean;
}

export interface PositionDisplayData {
  ticker: string;
  eventTicker: string;
  title: string;
  side: "yes" | "no";
  contracts: number;
  avgPrice: number; // cents
  currentPrice: number; // cents
  unrealizedPnl: number; // cents
  marketExposure: number; // cents
}

export interface OrderFormData {
  side: "yes" | "no";
  price: number; // cents (1-99)
  contracts: number;
}

export type CredentialStatus = "connected" | "disconnected" | "loading";

export interface PortfolioSummary {
  balance: number; // cents
  portfolioValue: number; // cents
  totalPnl: number; // cents
  positionCount: number;
}

export const CATEGORIES = [
  "All",
  "Geopolitics",
  "Economy",
  "US Politics",
  "World Politics",
] as const;

export type MarketCategory = (typeof CATEGORIES)[number];
