# Regional web QA with Playwright

A provider-neutral B2B evidence runner for sites your organization owns or is
explicitly authorized to test from an agreed proxy region. Chromium produces a
private PNG screenshot and a sanitized JSON report.

Security defaults:

- HTTPS target on the default port;
- exact hostname allowlists without wildcards;
- context-level policy for navigation, frames, and subresources;
- separate `RESOURCE_ALLOWED_HOSTS` for CDN/API dependencies;
- private, loopback, and link-local targets require explicit opt-in;
- popups are closed;
- Service Workers are blocked so they cannot bypass request interception;
- WebSockets are blocked until a separate reviewed allowlist is implemented;
- non-proxied WebRTC UDP is disabled in Chromium;
- proxy endpoint, credentials, paths, queries, fragments, and page title are
  excluded from JSON by default;
- unique artifact names, file mode `0600`, directory mode `0700`.
- fixed `1440×900` viewport, full-page capture disabled, and a 10 MiB PNG cap.

Run:

```bash
npm ci
npx playwright install chromium
cp .env.example .env
npm start
```

Set proxy credentials only in `PROXY_USERNAME` and `PROXY_PASSWORD`.
`ALLOWED_HOSTS` controls navigation; `RESOURCE_ALLOWED_HOSTS` controls all other
network resources and defaults to the navigation list.

Offline verification:

```bash
npm test
npm run check
```

The opt-in browser run is `npm run test:e2e`. Stable exit codes are `0` passed,
`1` unexpected, `2` configuration, `3` browser unavailable, `4` navigation or
policy, `5` HTTP assertion, and `6` artifact write.

Screenshots can still contain page data. Use test accounts, private artifact
storage, retention limits, and only authorized targets. This example is not for
bypassing anti-bot systems or access controls. Full guidance is in the
[Russian README](README.md).

Browser interception is not a network firewall. Run the real check in an
isolated worker whose network policy denies direct outbound traffic and permits
only the proxy endpoint plus reviewed infrastructure.
