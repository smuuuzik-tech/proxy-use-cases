# Proxy Use Cases

[Русская версия](README.md)

Provider-neutral, runnable solutions for business proxy workloads: from a first
connectivity smoke test to a production HTTP client, proxy-pool monitoring, and
evidence-oriented regional web QA.

The project is maintained by Andrey for developers, technical leaders, DevOps,
SRE, and platform teams. The core solutions remain provider-neutral; public API
specifics live in separate technical studies.

## Choose a level

| Level | Goal | Runnable solution |
|---|---|---|
| 1. Connectivity | Verify routing, authentication, and observed egress IP | [cURL quickstart](quickstarts/curl/) |
| 2. Integration | Send B2B HTTP requests with timeouts, a retry budget, and JSON results | [Python production client](integrations/python-production/) |
| 3. Operations | Measure success rate, p95 latency, IP rotation, and pool health | [Proxy Healthcheck](tools/proxy-healthcheck/) |
| 3/4. Business workflow | Test an authorized site from an agreed region and retain evidence | [Regional Web QA](use-cases/regional-web-qa/) |

All four solutions include offline tests and require no real credentials for
code verification.

## B2B operating model

- [Maturity model](docs/B2B-MATURITY-MODEL.md)
- [Reference architecture](docs/B2B-REFERENCE-ARCHITECTURE.md)
- [SLO and incident runbook template](docs/B2B-SLO-AND-RUNBOOK.md)
- [Proxy.Market API 1.1](integrations/proxy-market-api/) — a vendor-specific
  technical study and defensive B2B client.

## Engineering defaults

- Standard HTTP/SOCKS interfaces; no provider-specific SDK.
- Credentials are kept separate from URLs and public output.
- HTTPS by default; insecure or private targets require explicit opt-in.
- Bounded timeouts, concurrency, response size, and retry count.
- Proxy checks cannot be silently bypassed by `NO_PROXY`.
- Retries are constrained by idempotency and a retry budget.
- Paths, queries, credentials, and sensitive errors are removed from reports.
- Examples are only for systems and data the organization is authorized to use.

GitHub Actions runs the shell, Python, and Node.js offline suites on every pull
request. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md) before contributing.
