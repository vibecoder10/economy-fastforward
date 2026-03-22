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
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "BrainState_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
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
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "BetExperiment_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "BrainState_userId_key" ON "BrainState"("userId");
