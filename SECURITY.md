# Security policy

## Reporting a vulnerability

Open a private security advisory on the repo:
https://github.com/arcbaslow/meta-ads-agents/security/advisories/new

Please do not file public issues for security problems.

## What's in scope

- Credential handling in `scripts/meta_auth.py` and any path that
  touches `~/.claude/meta-ads-credentials.json`
- The OAuth callback listener on `localhost:8477` — CSRF on the state
  parameter, callback hijacking, token leakage into the URL bar or
  shell history
- Long-lived token exchange: app secret handling in
  `exchange_for_long_lived_token`
- Anything that writes an access token, app secret, or ad account
  identifier into the response cache, a report file, or a log line
- Any code path that sends account data to a third-party endpoint
- Dependency-chain vulnerabilities in `facebook-business` or `fpdf2` as
  pinned in `scripts/requirements.txt`

## What's out of scope

- Misuse of the toolkit against an ad account you do not have
  legitimate access to
- Bugs in the upstream Meta Marketing API itself — report those to Meta
- Issues that require an attacker with shell access to the user's
  machine (they already own `~/.claude/` and the OS temp directory)

## Where credentials live on disk

- Access token and app credentials:
  `~/.claude/meta-ads-credentials.json` (file mode `0600` on POSIX;
  Windows relies on the user profile ACL)
- Cached API responses:
  `<system temp>/claude-meta-ads/` — 15-minute TTL

The toolkit never logs credentials to stdout, never sends them to a
third party, and never bakes them into report files.

Note that the response cache is written to the OS temp directory
without a restrictive mode. On a shared multi-user host, treat cached
ad-account data as readable by other local users. If that matters in
your environment, run with `--no-cache`.

## Token hygiene

Long-lived Meta tokens last 60 days. `meta_auth.py --check` reports the
stored expiry and warns as it approaches. Rotate the app secret in the
Meta App dashboard if you suspect exposure — revoking there
invalidates every derived token.

## Disclosure timeline

I aim to acknowledge security reports within 7 days and ship a fix or
mitigation within 30 days. For high-severity issues affecting active
users, both windows shrink.
