---
name: supabase-postgres-best-practices
description: Postgres performance optimization and best practices from Supabase. Use this skill when writing, reviewing, or optimizing Postgres queries, schema designs, or database configurations.
license: MIT
metadata:
  author: supabase
  version: "1.1.0"
  organization: Supabase
---

# Supabase Postgres Best Practices

Comprehensive performance optimization guide for Postgres, maintained by Supabase. Contains rules across 8 categories, prioritized by impact to guide automated query optimization and schema design.

## When to Apply

Reference these guidelines when:
- Writing SQL queries or designing schemas
- Implementing indexes or query optimization
- Reviewing database performance issues
- Configuring connection pooling or scaling
- Optimizing for Postgres-specific features
- Working with Row-Level Security (RLS)

## Rule Categories by Priority

| Priority | Category | Impact | Prefix |
|----------|----------|--------|--------|
| 1 | Query Performance | CRITICAL | `query-` |
| 2 | Connection Management | CRITICAL | `conn-` |
| 3 | Security & RLS | CRITICAL | `security-` |
| 4 | Schema Design | HIGH | `schema-` |
| 5 | Concurrency & Locking | MEDIUM-HIGH | `lock-` |
| 6 | Data Access Patterns | MEDIUM | `data-` |
| 7 | Monitoring & Diagnostics | LOW-MEDIUM | `monitor-` |
| 8 | Advanced Features | LOW | `advanced-` |

## Key Rules Quick Reference

### 1. Query Performance (CRITICAL)
- Always add indexes for columns used in WHERE, JOIN, ORDER BY
- Use partial indexes for frequently filtered subsets
- Avoid SELECT * — only fetch columns you need
- Use EXPLAIN ANALYZE to verify query plans
- Prefer EXISTS over COUNT for existence checks

### 2. Connection Management (CRITICAL)
- Use connection pooling (PgBouncer/Supavisor) in production
- Set appropriate pool sizes (not too large)
- Use transaction mode for serverless workloads
- Close connections promptly after use

### 3. Security & RLS (CRITICAL)
- Enable RLS on all user-facing tables
- Write policies that use indexes (avoid sequential scans)
- Test policies with `SET ROLE` to verify access
- Use `auth.uid()` in policies for row-level filtering

### 4. Schema Design (HIGH)
- Use appropriate data types (don't store numbers as text)
- Add NOT NULL constraints where applicable
- Use foreign keys for referential integrity
- Normalize data but denormalize for read performance where needed
- Use enums or check constraints for fixed value sets

### 5. Concurrency & Locking (MEDIUM-HIGH)
- Use `SELECT ... FOR UPDATE SKIP LOCKED` for job queues
- Avoid long-running transactions that block others
- Use advisory locks for application-level coordination

### 6. Data Access Patterns (MEDIUM)
- Batch inserts with multi-row VALUES
- Use UPSERT (ON CONFLICT) for idempotent writes
- Paginate with keyset pagination, not OFFSET
- Use materialized views for expensive aggregations

### 7. Monitoring & Diagnostics (LOW-MEDIUM)
- Monitor `pg_stat_statements` for slow queries
- Track index usage with `pg_stat_user_indexes`
- Set up alerts for connection pool saturation
- Log queries slower than a threshold

### 8. Advanced Features (LOW)
- Use JSONB for semi-structured data (with GIN indexes)
- Leverage generated columns for computed values
- Use table partitioning for very large tables
- Consider pg_cron for scheduled database tasks
