# Mantly Editions and Deployment Modes

Mantly separates **where the system runs** from **which commercial edition is
used**.

Deployment modes:

- `self_hosted`: operated by the customer from Community source.
- `cloud`: operated by Mantly as a shared managed service.
- `dedicated`: operated for one commercial customer in a dedicated environment.

Product editions:

- `community`: the complete safe open-source core.
- `business`: Community capabilities plus commercial team governance and
  service entitlements.
- `enterprise`: Business plus negotiated deployment, integration, procurement,
  and support terms.

The runtime exposes these dimensions separately through
`MANTLY_DEPLOYMENT_MODE` and `MANTLY_EDITION`. Legacy hosted billing identifiers
remain internal migration details and are not product-edition names.

## Current product boundary

| Capability | Community | Cloud | Business | Enterprise |
| --- | --- | --- | --- | --- |
| Inbox, multi-concern runbooks, one response composer | Included | Included | Included | Included |
| Knowledge Agent, tools, permitted actions | Included | Included | Included | Included |
| Human approvals, evaluations, execution history | Included | Included | Included | Included |
| Prompt-injection and phishing monitoring | Included | Included | Included | Included |
| Model keys and compatible custom gateways | Customer-operated | Supported | Supported | Negotiated |
| Hosting and application updates | Customer-operated | Mantly-operated | Mantly-operated option | Cloud, dedicated, or self-hosted |
| Projects | Unlimited locally | Hosted-plan allowance | 10 included today | Negotiated |
| Team members | Unlimited locally | Unlimited on paid Cloud | Unlimited | Unlimited |
| Support | Community channels | Standard support | Priority onboarding | Contract-specific |

Community has no license key, license server, Stripe dependency, or Mantly usage
limit. Its practical capacity is determined by the operator's infrastructure and
model provider.

Business and Enterprise do **not** currently promise SAML/SSO, SCIM, custom
roles, external secret managers, SIEM streaming, formal compliance reports,
high availability, disaster-recovery objectives, or an uptime SLA. Those
capabilities may be developed or agreed later; they must not be advertised as
available until implementation and operating commitments are verified.

## Agent-run billing unit

For hosted plans, one agent run is one inbound customer message processed by
Mantly. It counts once even when the message contains several concerns and
causes multiple runbooks, knowledge searches, tool calls, actions, or response
steps. Seats, concerns, tokens, and individual tool calls are not separate
agent-run units.

Managed model usage may have a separately disclosed allowance or provider-cost
charge. Customer-provided model keys are not Mantly-managed model usage.

## Licensing boundary

Community source is `AGPL-3.0-only`. Mantly Cloud is a service, while separately
developed commercial components and support contracts may use other terms.
External Community contributions stay under the Community license unless their
contributors separately and explicitly agree to different terms.

This matrix describes the current product boundary, not a contractual SLA or a
promise that every future feature will use the same packaging.
