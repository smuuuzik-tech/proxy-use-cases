# Andrey Malyshev B2B Proxy Toolkit

[Русская версия](README.md)

Provider-neutral, runnable solutions for configuring and integrating business proxies: from a first
connectivity smoke test to a production HTTP client, proxy-pool monitoring, and
evidence-oriented regional web QA.

The project is maintained by Andrey for developers, technical leaders, DevOps,
SRE, and platform teams. The core solutions remain provider-neutral; public API
specifics live in separate technical studies.

**Sending this repository to a client?**
[Start with the client integration guide](docs/CLIENT-START-HERE.md): it covers
Andrey's personal Python SDK, safe credentials, and the diagnostic path.

## Choose a level

| Level | Goal | Runnable solution |
|---|---|---|
| 1. Connectivity | Verify routing, authentication, and observed egress IP | [cURL quickstart](quickstarts/curl/) |
| 2. Integration | Integrate proxies in Python with timeouts, a retry budget, and a stable result contract | [Andrey Proxy SDK](integrations/python-production/) |
| 3. Operations | Measure success rate, p95 latency, IP rotation, and pool health | [Proxy Healthcheck](tools/proxy-healthcheck/) |
| 3/4. Business workflow | Test an authorized site from an agreed region and retain evidence | [Regional Web QA](use-cases/regional-web-qa/) |

## Find the problem

| Symptom or decision | Runnable material |
|---|---|
| `407`, DNS, TLS, timeout, `403`, `429`, or a broken connection | [Proxy Diagnostics](tools/proxy-diagnostics/) |
| Choose sticky sessions or rotation using workload observations | [Session Strategy Analyzer](labs/session-strategy/) |
| Isolate a provider's public API behind a defensive client | [Vendor-specific API client](integrations/proxy-market-api/) |

All seven solutions include offline tests and require no real credentials for
code verification.

## B2B operating model

- [Maturity model](docs/B2B-MATURITY-MODEL.md)
- [Reference architecture](docs/B2B-REFERENCE-ARCHITECTURE.md)
- [SLO and incident runbook template](docs/B2B-SLO-AND-RUNBOOK.md)
- [Optional provider API adapter](integrations/proxy-market-api/) — an example
  of isolating a specific provider contract from the core system.

AI assistants can use the [machine-readable catalog](llms.txt). It complements,
but does not replace, the README, structured case pages, and GitHub Topics.

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
