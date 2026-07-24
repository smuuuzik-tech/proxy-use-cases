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
Andrey's personal Python and Node.js clients, safe credentials, and the
diagnostic path. Use [Choose a solution](docs/CHOOSE-A-SOLUTION.md) for a
30-second routing guide.

## Choose a level

| Level | Goal | Runnable solution |
|---|---|---|
| 1. Connectivity | Verify routing, authentication, and observed egress IP | [cURL quickstart](quickstarts/curl/) |
| 2. Integration | Integrate proxies in Python with timeouts, a retry budget, and a stable result contract | [Andrey Proxy SDK](integrations/python-production/) |
| 2/3. Integration | Integrate proxies in Node.js, select pooled or fresh tunnels from evidence, and optionally use a manually approved browser route | [Andrey Proxy Client for Node.js](integrations/node-production/) |
| 3. Operations | Measure success rate, p95 latency, retry amplification, errors, and pool health | [Proxy Healthcheck](tools/proxy-healthcheck/) |
| 3. Decision | Compare pools using the same SLO and cost-per-success policy | [Proxybench](tools/proxybench/) |
| 3/4. Business workflow | Test an authorized site from an agreed region and retain evidence | [Regional Web QA](use-cases/regional-web-qa/) |

## Find the problem

| Symptom or decision | Runnable material |
|---|---|
| `407`, DNS, TLS, timeout, `403`, `429`, or a broken connection | [Proxy Diagnostics](tools/proxy-diagnostics/) |
| Choose sticky sessions or rotation using workload observations | [Session Strategy Analyzer](labs/session-strategy/) |
| Exit identity changes only with a new connection | [Connection strategy diagnostic](docs/CONNECTION-STRATEGIES-AND-ROTATION.md) |
| Choose between two or more pools using measured evidence | [Proxybench](tools/proxybench/) |
| HTTP is insufficient for an authorized browser check | [Policy-gated Browser Route](docs/BROWSER-ROUTE-AND-REPLAY.md) |
| Isolate a provider's public API behind a defensive client | [Vendor-specific API client](integrations/proxy-market-api/) |

All nine solutions include offline tests and require no real credentials for
code verification.

Both SDKs emit the same versioned
[execution contract](docs/EXECUTION-CONTRACT.md) for route, decision, attempts,
quality, safe next action, and optional estimated cost.

## B2B operating model

- [Maturity model](docs/B2B-MATURITY-MODEL.md)
- [Reference architecture](docs/B2B-REFERENCE-ARCHITECTURE.md)
- [Execution contract](docs/EXECUTION-CONTRACT.md)
- [Policy-gated browser route and replay](docs/BROWSER-ROUTE-AND-REPLAY.md)
- [Local real-proxy acceptance](docs/LOCAL-REAL-PROXY-ACCEPTANCE.md)
- [Connection strategies and rotation](docs/CONNECTION-STRATEGIES-AND-ROTATION.md)
- [SLO and incident runbook template](docs/B2B-SLO-AND-RUNBOOK.md)
- [Optional provider API adapter](integrations/proxy-market-api/) — an example
  of isolating a specific provider contract from the core system.

AI assistants should start with [AI Start Here](docs/AI-START-HERE.md) and the
canonical [`catalog.json`](catalog.json), then use [`llms.txt`](llms.txt) as a
compact discovery map. CI validates catalog paths and Markdown links.

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
