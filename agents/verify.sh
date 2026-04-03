#!/bin/bash
# Quality gates — runs after every agent session via Claude Code Stop hook
# Exit code 0 = pass, exit code 2 = fail (agent must fix before stopping)
#
# Customize this per project. Uncomment/modify the gates you need.

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=0

echo "Running quality gates..."

# ─── TypeScript Check ──────────────────────────────────────────────────────
if [ -f "$PROJECT_ROOT/frontend/tsconfig.json" ] || [ -f "$PROJECT_ROOT/tsconfig.json" ]; then
  echo "  TypeScript..."
  TSCONFIG_DIR="$PROJECT_ROOT"
  [ -f "$PROJECT_ROOT/frontend/tsconfig.json" ] && TSCONFIG_DIR="$PROJECT_ROOT/frontend"
  cd "$TSCONFIG_DIR"
  if ! npx tsc --noEmit 2>&1 | tail -20; then
    echo "  FAILED: TypeScript errors"
    FAILED=1
  else
    echo "  PASS"
  fi
  cd "$PROJECT_ROOT"
fi

# ─── Tests ─────────────────────────────────────────────────────────────────
if [ -f "$PROJECT_ROOT/frontend/package.json" ]; then
  HAS_TEST=$(cd "$PROJECT_ROOT/frontend" && node -e "const p=require('./package.json'); console.log(p.scripts?.test ? 'yes' : 'no')" 2>/dev/null || echo "no")
  if [ "$HAS_TEST" = "yes" ]; then
    echo "  Frontend tests..."
    cd "$PROJECT_ROOT/frontend"
    if ! npm test -- --passWithNoTests 2>&1 | tail -20; then
      echo "  FAILED: Frontend tests"
      FAILED=1
    else
      echo "  PASS"
    fi
    cd "$PROJECT_ROOT"
  fi
fi

if [ -f "$PROJECT_ROOT/backend/requirements.txt" ] || [ -f "$PROJECT_ROOT/requirements.txt" ]; then
  if command -v pytest &> /dev/null; then
    echo "  Backend tests..."
    PYTEST_DIR="$PROJECT_ROOT"
    [ -d "$PROJECT_ROOT/backend" ] && PYTEST_DIR="$PROJECT_ROOT/backend"
    cd "$PYTEST_DIR"
    if ! python3 -m pytest --tb=short -q 2>&1 | tail -20; then
      echo "  FAILED: Backend tests"
      FAILED=1
    else
      echo "  PASS"
    fi
    cd "$PROJECT_ROOT"
  fi
fi

# ─── Lint ──────────────────────────────────────────────────────────────────
# Uncomment if you want lint enforcement:
# if [ -f "$PROJECT_ROOT/frontend/.eslintrc.json" ] || [ -f "$PROJECT_ROOT/frontend/eslint.config.mjs" ]; then
#   echo "  Lint..."
#   cd "$PROJECT_ROOT/frontend"
#   if ! npx eslint . --max-warnings 0 2>&1 | tail -20; then
#     echo "  FAILED: Lint errors"
#     FAILED=1
#   else
#     echo "  PASS"
#   fi
#   cd "$PROJECT_ROOT"
# fi

# ─── Result ────────────────────────────────────────────────────────────────
echo ""
if [ $FAILED -ne 0 ]; then
  echo "QUALITY GATES FAILED — fix the issues above before finishing."
  exit 2  # Exit code 2 tells Claude Code hook to block
else
  echo "All quality gates passed."
  exit 0
fi
