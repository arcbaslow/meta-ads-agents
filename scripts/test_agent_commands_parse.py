"""Every command an agent is told to run must parse against its own adapter.

The agent definitions under `agents/` and the skill bodies under `skills/`
are prose, so nothing checked they matched the CLIs they invoke. All seven
agents and the audit skill were passing `--json`, which no adapter defined -
so each one exited 2 on its very first command and the whole skill to agent
to adapter chain was dead.

This walks the markdown, pulls out every `python scripts/<x>.py ...` line,
and asserts the adapter's own parser accepts it. It is the cheapest possible
guard against documentation drifting away from argparse.

Two details that matter, both learned the hard way:

- Do not append `--help`. argparse fires the help action and exits 0 the
  moment it sees it, before the unrecognized-argument check runs at the end
  of parse_args. A `--help`-based version of this test passes even with the
  flag removed, which is worse than no test.
- Run with HOME and USERPROFILE redirected. Without that the subprocess
  resolves the real `~/.claude/meta-ads-credentials.json` and a passing
  parse would go on to hit the live Meta API.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

_CMD_RE = re.compile(r"python\s+scripts/(meta_\w+\.py)([^`\n]*)")

_PLACEHOLDER = {
    "<id>": "act_123456789",
    "<account-id>": "act_123456789",
    "<url>": "https://example.com",
    "<path>": "out.json",
    "<file>": "out.json",
}

# argparse exits 2 on a usage error: unknown flag, bad choice, missing required.
_ARGPARSE_USAGE_ERROR = 2


def _documented_commands():
    out = []
    roots = [REPO_ROOT / "agents", REPO_ROOT / "skills"]
    for root in roots:
        for md in sorted(root.rglob("*.md")):
            for line_no, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
                for script, tail in _CMD_RE.findall(line):
                    out.append((f"{md.relative_to(REPO_ROOT)}:{line_no}", script, tail.strip()))
    return out


DOCUMENTED = _documented_commands()


def test_the_scan_actually_found_commands():
    """Guard the guard: a broken regex would make every case below vacuous."""
    assert len(DOCUMENTED) >= 15, f"only found {len(DOCUMENTED)} documented commands"


@pytest.mark.parametrize(
    "where,script,tail",
    DOCUMENTED,
    ids=[f"{w}:{s}" for w, s, _ in DOCUMENTED],
)
def test_documented_command_parses(where, script, tail, tmp_path):
    assert (SCRIPTS / script).exists(), f"{where} references a script that does not exist"

    args = [_PLACEHOLDER.get(tok, tok) for tok in shlex.split(tail, posix=False)]

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {
        "PATH": "",
        "SYSTEMROOT": "",
        "HOME": str(fake_home),
        "USERPROFILE": str(fake_home),
        "PYTHONPATH": str(SCRIPTS),
    }

    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS),
        env=env,
        timeout=60,
    )

    # The adapter will still fail afterwards - no credentials under the fake
    # home - and that is fine. We only care that argparse accepted the line.
    assert proc.returncode != _ARGPARSE_USAGE_ERROR, (
        f"{where} documents a command its adapter rejects:\n"
        f"  python scripts/{script} {tail}\n"
        f"  stderr: {proc.stderr.strip()}"
    )
    assert "unrecognized arguments" not in proc.stderr, (
        f"{where}: {proc.stderr.strip()}"
    )
    assert "invalid choice" not in proc.stderr, f"{where}: {proc.stderr.strip()}"
