# Demo Mode

Demo mode is local/internal only. It is off by default and must stay off for
SaaS and customer on-prem production.

## Enable locally

Use env flags, not code edits:

```env
VITE_ENABLE_DEMO_MODE=true
VITE_ENABLE_MOCK_MODE=true
```

The legacy `VITE_ENABLE_DEMO_SCENARIOS=true` flag is still accepted for local
compatibility, but new configs should use `VITE_ENABLE_DEMO_MODE=true`.

Demo scenarios only load in Vite development mode. Production builds do not
activate the add-in demo picker.

## Related backend/admin flag

Backend seeded routes are controlled separately:

```env
ENABLE_DEMO_MODE=true
```

Admin onboarding shows the “Load demo pipeline” action only when built with:

```env
VITE_ENABLE_DEMO_MODE=true
```

Keep all three flags unset or false in production.

## Demo data

Central demo data lives under repo-root `demo/`:

- `demo/emails/emails.json` — add-in scenarios.
- `demo/crm/customers.json` — seeded CRM records.
- `demo/actions/responses.json` — seeded webhook response templates.
- `demo/pipelines/insurance-claim.json` — admin “Load demo pipeline” data.

The add-in, admin UI, and backend use thin adapters around those JSON files.
