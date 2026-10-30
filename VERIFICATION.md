# Verification report — ZUDO SMM PANEL

Verification date: 2026-10-30. This report describes executed checks, not promised future tests.

## Executed successfully

| Check | Result / scope |
| --- | --- |
| Node runtime | Node 22.23.4, npm 10.9.9 |
| Clean production dependency install | npm ci --omit=dev in a separate clean copy; passed |
| Production build validation | npm run build; checked JavaScript syntax and required assets; passed |
| Production startup | NODE_ENV=production npm start; migrations, owner provisioning, HTTP listen and health; passed locally |
| Actual PostgreSQL | PostgreSQL 16; integration schema and independent production-verification database |
| Integration tests | 25 passed, 0 failed, 0 skipped; actual PostgreSQL and a local test-only provider |
| Browser checks | 9 scenario groups passed in headless Chromium; no JavaScript/CSP errors recorded |
| Responsive checks | Landing at 320/390/768/1024/1440px; customer and owner sections at mobile/desktop widths; no page-wide overflow |
| Production HTTPS cookies | __Host-zudo.sid secure + HttpOnly verified through a local HTTPS proxy |
| Sessions after process restart | Saved authenticated owner session remained valid after stopping the original server and starting a clean production installation against the same PostgreSQL database |
| Read-only live provider | Supplied real API key accepted for balance and services; reported INR and 242 catalogue entries at initial verification |
| Live catalogue and quotes | Browser searched real catalogue, selected a real service, and obtained an INR server-side quote without placing a paid order |
| Render Blueprint | render.yaml parsed and validated against Render's published JSON schema; current compute plan identifiers used |
| Dependency audit | npm audit --omit=dev reported 0 vulnerabilities at verification time |
| Source credential scan | No supplied real provider API key or supplied owner password in repository files |

## Integration coverage

Health, static assets, customer registration/login/logout, separate owner authentication, username uniqueness, password confirmation, password hashing, reserved owner username, password changes, invalidation of older sessions, CSRF, configured-origin rejection, protected routes, role authorization, user isolation and suspension.

Atomic and concurrent owner credits/debits, idempotency references, insufficient funds, nonnegative balances, UTR normalization/uniqueness, pending deposits not crediting wallets, concurrent deposit approvals crediting exactly once, deposit rejection not crediting wallets, and full ledger-to-balance equality.

Dynamic services, 60% default markup, pricing changes applying only to future orders, stale-quote rejection, checkout quantity bounds, required media, unsafe-link validation, Package one-time rates, decimal/paise rounding, concurrent duplicate-order submission producing one provider add call, provider rejection/full refund, ambiguous responses with reserved funds, manual refund and provider-ID reconciliation, completed status updates, cancellation/full refunds, partial/proportional refunds, and idempotent repeated status checks.

Owner statistics, user search, paginated individual order and transaction histories, all orders, deposits, pricing settings, audit records; support creation, cross-user access protection, owner reply, ticket closure; SQL-injection-shaped search and invalid amount input; missing API/page routes.

## Browser coverage

Landing and mobile layout; registration; secure sessions; dashboard and customer sections; mobile navigation; live services/search/filter controls and quote; local UTR request; support ticket; environment-supplied owner login; owner credit and deduction with confirmation; local deposit rejection; owner pages; support reply; refresh persistence and logout. Browser actions were performed against a disposable local PostgreSQL database, not a public customer installation. Test UTR submissions did not represent real payments.

## Explicit limits — do not misinterpret these checks

1. No actual Render-account deployment was performed. An authenticated Render/GitHub account deployment, Render's remote runtime, external DNS and domain/TLS provisioning are not verified by a local production run or a Blueprint schema check.
2. No paid live-provider order, refill or cancellation was sent. Order lifecycle/charges/refunds were exercised against the isolated test provider, using real application transactions and PostgreSQL. Read-only live balance/catalogue calls and local quote calculations were verified separately.
3. No real UPI transfer or bank settlement was verified. Payment approval is deliberately manual; the owner must compare settled funds against their own bank records.
4. Live Subscriptions entries are visible but not orderable. The provider's public add-order documentation does not document a recurring subscription contract. Default, Package and Mentions Media Likers checkout contracts are implemented. Subscription checkout is not claimed complete.
5. This is not an independent security penetration test, a financial audit, a load/availability guarantee, or a guarantee of provider delivery. There was no high-volume load test or multi-instance distributed limiter test.
6. Provider cost and profit totals are estimates from order snapshots/refund proportions, not verified provider settlement. External fees and taxes are not calculated.
7. Manual reconciliation of uncertain provider submissions depends on correct owner verification. The provider does not document end-to-end client idempotency, so automatic re-submission is intentionally disabled.

## Evidence included

- verification/integration.tap: executed Node test output
- verification/browser-results.json: executed browser scenario summary
- verification/production-start.log: clean production startup log
- CHECKSUMS.sha256: source file digests (excluding this digest file itself)

External documentation checked:

- Provider: https://mysmm.org/api
- Exact production API: https://mysmm.org/api/v2
- Render Blueprint reference: https://render.com/docs/blueprint-spec
- Render Blueprint JSON schema: https://render.com/schema/render.yaml.json
- Render PostgreSQL connections: https://render.com/docs/postgresql-creating-connecting
