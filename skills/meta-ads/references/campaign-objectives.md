# Meta Campaign Objectives (ODAX)

## Current Objectives (Outcome-Driven Ad Experiences)

| Objective | API Value | Best For |
|-----------|-----------|----------|
| Awareness | OUTCOME_AWARENESS | Brand reach, impressions, video views |
| Traffic | OUTCOME_TRAFFIC | Website visits, landing page views |
| Engagement | OUTCOME_ENGAGEMENT | Post engagement, page likes, event responses |
| Leads | OUTCOME_LEADS | Lead forms, Messenger, instant forms |
| App Promotion | OUTCOME_APP_PROMOTION | App installs, app events |
| Sales | OUTCOME_SALES | Conversions, catalog sales, ROAS |

## Optimization Events by Objective

### OUTCOME_SALES
- Purchase (recommended for ROAS campaigns)
- Add to Cart (if purchase volume < 50/week)
- Initiate Checkout
- Value optimization (requires 100+ purchases/week)

### OUTCOME_LEADS
- Lead (form submissions)
- Complete Registration
- Contact
- Conversion leads (requires CRM integration)

### OUTCOME_TRAFFIC
- Landing page views (recommended over link clicks)
- Link clicks

### OUTCOME_APP_PROMOTION
- App installs
- App events (post-install actions)

## Conversion-Optimized Objectives

These objectives indicate the account uses conversion tracking and attribution:
- OUTCOME_SALES
- OUTCOME_LEADS
- OUTCOME_APP_PROMOTION

Use these to determine whether to spawn the meta-attribution agent.

## Bid Strategies

| Strategy | When to Use |
|----------|-------------|
| Lowest cost | Default, good for most campaigns |
| Cost cap | When you have a strict CPA target |
| Bid cap | Maximum control, requires expertise |
| ROAS goal | When optimizing for return on ad spend |
| Highest value | Maximize conversion value within budget |
