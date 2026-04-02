---
name: Deploy
description: Deploy applications to production. Handles build, test, and release steps.
---

# Deploy

When deploying:

1. Run the test suite — do not deploy if tests fail
2. Build the production bundle
3. Deploy to the configured target (check .env for deployment config)
4. Verify the deployment is live and healthy
5. Report back with the deployment URL and status
