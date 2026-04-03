# Security Auditor Memory
- Initial audit (2026-04-03): 6 security issues found in pre-audit. SEC-1 through SEC-6. Check if fixed before creating duplicates.
- Full audit (2026-04-03): SEC-1 through SEC-6 all still present. Fixed SEC-2 (audio endpoint auth). Added SEC-7 (token in URL) and SEC-8 (unvalidated redirects). Filed all as tasks in tab 26.
- Pattern: auth.py dev-token backdoor defaults to active. Any server without ENV=production is vulnerable. This is the #1 risk.
- Pattern: HTML Audio elements can't set Authorization headers — audio proxy endpoints need query token auth with JWT validation.
- Pattern: f-string SQL is used in 6+ route files for dynamic SET clauses. Currently safe via whitelists but fragile.
