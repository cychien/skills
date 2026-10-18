# Plan capacity

Capacity is how much agent work a subscription can absorb. It is the plan's size relative to the same provider's entry paid plan, which is the 1x plan. Plans and limits change often, so these rows are a starting point: when a plan is missing here, or the provider's pricing page disagrees, trust the page.

## Levels

| Multiple of the 1x plan | Capacity |
|---|---|
| under 1x, or no access to the agent CLI | none |
| 1x | small |
| 5x to under 20x | medium |
| 20x or more | large |

`unlimited` applies only when the user says the agent has no spending cap.

## Plans

| Provider | Plan | Multiple |
|---|---|---|
| Claude | Free | none |
| Claude | Pro | 1x |
| Claude | Team, standard seat | 1x |
| Claude | Team, premium seat | 5x |
| Claude | Max 5x | 5x |
| Claude | Max 20x | 20x |
| ChatGPT (Codex) | Free, Go | none |
| ChatGPT (Codex) | Plus | 1x |
| ChatGPT (Codex) | Business | 1x |
| ChatGPT (Codex) | Pro | 5x or 20x, by the tier on the pricing page |
| Cursor | Pro | 1x |
| Cursor | Pro+ | 3x |
| Cursor | Ultra | 20x |
| Gemini | AI Pro | 1x |
| Gemini | AI Ultra | by the pricing page |

## 1x prices

Last known monthly prices, for turning an unlisted plan's price into a multiple. Check the pricing page when it can be reached.

| Provider | 1x plan | Monthly price |
|---|---|---|
| Claude | Pro | $20 |
| ChatGPT (Codex) | Plus | $20 |
| Cursor | Pro | $20 |
| Gemini | AI Pro | $20 |

## Plans not listed

1. Look up the provider's pricing page for the plan's price and stated usage limits.
2. Divide the plan's monthly price by the 1x price. Use that multiple in the Levels table.
3. When the page cannot be reached, ask the user for the monthly price and do the same division.
4. Enterprise and other negotiated plans have no public price. Ask the user whether the agent has a spending cap, and treat a cap as medium and no cap as unlimited.

## Metered API keys

There is no plan size, so ask the monthly spend the user is comfortable with, and record it as `monthly_usd`. Never divide it by a plan price: subscriptions are priced below the API rate for the same work, and 2026 usage reports put a 1x plan at roughly $75 of metered API use a month (Max 5x users report $100 to $1,000, Max 20x users $1,000 to $5,000). Map the spend directly:

| Monthly API spend | Capacity |
|---|---|
| under $300 | small |
| $300 to under $1,500 | medium |
| $1,500 or more | large |
| no cap | unlimited |
