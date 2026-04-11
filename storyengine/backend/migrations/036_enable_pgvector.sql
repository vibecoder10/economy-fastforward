-- Migration 036: Enable pgvector extension for content intelligence
-- This enables vector similarity search on distilled content embeddings.

CREATE EXTENSION IF NOT EXISTS vector;
