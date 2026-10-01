---
name: meta-ads-changes
description: "Change history correlated with performance. Reads the ad account activity log and compares each entity's metrics before and after every change. Use when user says 'what changed', 'why did it drop', 'who edited', 'change history', 'activity log', 'before and after'."
user-invokable: true
argument-hint: "<account-id> [--days N] [--window N] [--level adset|ad] [--action-type TYPE]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Change History

**Invocation:** `/meta-ads changes <account-id>` or "What changed before CPA went up?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-changes` agent with the account ID and the user's question
3. Agent runs `python scripts/meta_changes.py --account <id> --days 14 --window 3 --json`
4. Present the changes that were followed by a shift, largest first, with before and after numbers
5. Separate pauses and resumes, which move spend by definition

## Default Parameters
- `--days 14`: days of change history
- `--window 3`: days compared on each side of a change
- `--level adset`: campaign and ad set changes. `--level ad` adds ad and creative changes.
- `--threshold 30`: percent change that counts as a shift
- `--action-type`: optional insights action type, adds results and CPA

## Limits

A shift after a change is a correlation. The report says what moved together and leaves the cause to the reader. How far back the activity log goes is set by Meta and is not documented, so a long `--days` can return fewer entries than expected.
