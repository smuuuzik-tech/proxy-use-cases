# Instructions for AI coding agents

This is a public, client-facing repository of runnable B2B proxy solutions.

Before changing code:

1. Read `docs/AI-START-HERE.md`.
2. Select the solution through `catalog.json`.
3. Treat its README and tests as the executable contract.

Rules:

- Keep the default path provider-neutral.
- Never add real credentials, client data, private targets, internal plans, or
  competitor research.
- Do not weaken redaction, target policy, timeouts, response limits, retry
  budgets, idempotency checks, or destructive-operation guards.
- Every new solution needs offline tests, a README, a catalog entry, and links
  from `llms.txt` and both root README files.
- Run both scripts in `scripts/` before proposing changes.
