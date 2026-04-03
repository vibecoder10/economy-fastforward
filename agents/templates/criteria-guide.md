# Writing Machine-Verifiable Acceptance Criteria

Every task needs acceptance criteria that a machine can check. The criteria are shell commands that exit 0 on success.

## Good Criteria (machine can verify)

### API Endpoint Tests
```bash
# Check status code
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/users | grep -q 200

# Check response has expected field
curl -s http://localhost:8001/api/users | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'users' in d"

# Check POST creates a resource
curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8001/api/users -H 'Content-Type: application/json' -d '{"email":"test@test.com"}' | grep -q 201

# Check error handling
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/users/nonexistent | grep -q 404
```

### Database Checks
```bash
# Column exists
psql "$DATABASE_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_name='users'" | grep -q email

# Table exists
psql "$DATABASE_URL" -c "SELECT 1 FROM information_schema.tables WHERE table_name='users'" | grep -q 1
```

### Frontend Checks
```bash
# TypeScript compiles
cd frontend && npx tsc --noEmit

# File exists
test -f frontend/src/app/login/page.tsx

# Build succeeds
cd frontend && npm run build
```

### Browser Tests (Playwright)
```bash
# Page renders
npx playwright test tests/login.spec.ts

# Specific flow
npx playwright test -g "login redirects to dashboard"
```

### File/Code Checks
```bash
# File exists
test -f backend/routes/auth.py

# File contains expected pattern
grep -q "app.include_router" backend/main.py

# Import exists
grep -q "from routes.auth import" backend/main.py
```

## Bad Criteria (machine CANNOT verify)

- "Works correctly" (what does "correctly" mean?)
- "UI looks good" (subjective)
- "Handles edge cases" (which ones?)
- "Properly validates input" (what validation? what input?)
- "Is secure" (against what threats?)

## Rules

1. Every criterion is a shell command that exits 0 on success
2. No subjective criteria — if a human needs to judge it, it's not verifiable
3. Test the behavior, not the implementation — don't check "file has 50 lines"
4. Include both happy path AND error handling criteria
5. Browser tests use Playwright, not manual inspection
