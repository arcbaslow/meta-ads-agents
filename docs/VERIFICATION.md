# Release verification — v1.1.0

Date: 2026-10-01. Local environment: Windows, Python 3.12.10, facebook-business 26.0.2.

271 tests passed. Ruff passed.

| Check | Command | Result |
| --- | --- | --- |
| Tests | `python -m pytest scripts/ -q` | Passed |
| Ruff | `python -m ruff check scripts/` | Passed |

On the machine used, the default pytest temp directory was not writable, so the suite was run with `--basetemp` set to another directory. The tests themselves were unchanged.

## What the tests cover

- Every fetch function runs against a recording stand-in for the ad account, and each requested field is checked against the installed SDK's field list for that object (`scripts/test_requested_fields.py`).
- The delivery, change history and fatigue analyses are tested on synthetic data, including that their output does not depend on input order and that every API call goes through the response cache.
- Error output and the retry log are tested not to contain the access token.
- Every command documented in `agents/` and `skills/` is parsed against its adapter.

## Documentation and examples

- Executed the offline example commands from README against committed synthetic fixtures.
- Checked local README links and release versions.
- Built the release artifacts before publishing. Source archives contain only tracked repository files.

## Scope

The test results above are a dated local run on one Python version. The CI matrix runs Python 3.10 to 3.13. API responses are mocked. No call was made to the live Meta API, so behaviour that depends on live responses is not verified here: the shape of pixel stats rows, how far back the activity log goes, and the error the API returns for an unknown field. The [roadmap](ROADMAP.md) lists these under "Could not verify".

## Build artifacts

Source distribution and wheel built successfully; `twine check` passed. The wheel contains the ten adapter modules.
