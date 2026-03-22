-- CreateTable
CREATE TABLE "KalshiCredentials" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "apiKeyId" TEXT NOT NULL,
    "privateKey" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "WatchlistItem" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "eventTicker" TEXT NOT NULL,
    "marketTicker" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT '',
    "addedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "TradeLog" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "kalshiOrderId" TEXT NOT NULL,
    "marketTicker" TEXT NOT NULL,
    "eventTicker" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "contracts" INTEGER NOT NULL,
    "pricePerContract" REAL NOT NULL,
    "totalCost" REAL NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "BrainState" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "mode" TEXT NOT NULL DEFAULT 'paper',
    "bankrollCents" INTEGER NOT NULL DEFAULT 10000,
    "startingBankrollCents" INTEGER NOT NULL DEFAULT 10000,
    "totalBets" INTEGER NOT NULL DEFAULT 0,
    "wins" INTEGER NOT NULL DEFAULT 0,
    "losses" INTEGER NOT NULL DEFAULT 0,
    "totalPnlCents" INTEGER NOT NULL DEFAULT 0,
    "activeBets" TEXT NOT NULL DEFAULT '[]',
    "lastCycle" DATETIME,
    "lastBet" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "BetExperiment" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "ticker" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "contracts" INTEGER NOT NULL,
    "entryPrice" REAL NOT NULL,
    "totalCost" REAL NOT NULL,
    "confidence" REAL NOT NULL,
    "reasoning" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "mode" TEXT NOT NULL DEFAULT 'paper',
    "result" TEXT,
    "payout" REAL,
    "pnl" REAL,
    "learnings" TEXT,
    "settledAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE UNIQUE INDEX "KalshiCredentials_userId_key" ON "KalshiCredentials"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "WatchlistItem_userId_marketTicker_key" ON "WatchlistItem"("userId", "marketTicker");

-- CreateIndex
CREATE UNIQUE INDEX "BrainState_userId_key" ON "BrainState"("userId");
