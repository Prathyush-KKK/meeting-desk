"""scripts/mac-launch.sh: the Bedrock checks accept the nutrition service's bearer form.

The script runs for real in a scratch copy of the repo root, with ``docker`` and ``curl`` stubbed on
PATH: the stub records the compose call and the ``EXTRAS`` it was built with, and ``curl`` answers
the health poll at once. Nothing is built, started or fetched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mac-launch.sh"

BASE_URL = "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
TOKEN = "ABSKQmVkcm9ja0FQSUtleS10ZXN0LWtleQ=="
GEMMA = "google.gemma-4-26b-a4b"
CLAUDE = "anthropic.claude-3-5-sonnet-20240620-v1:0"

BASE_ENV = """\
BOOTSTRAP_ADMINS=prathyush.kodhanpur@simpleo.ai
GOOGLE_HOSTED_DOMAIN=simpleo.ai
GOOGLE_CLIENT_ID=client-id
GOOGLE_CLIENT_SECRET=client-secret
SESSION_SECRET=already-generated-session-secret-value
MEETING_DESK_TOKEN_KEY=already-generated-token-key
PUBLIC_URL=http://localhost:8000
FAKE_LLM=0
BEDROCK_REGION=ap-south-1
"""

STUB_DOCKER = """#!/bin/sh
echo "docker $* EXTRAS=${EXTRAS-<unset>}" >>"$STUB_LOG"
exit 0
"""


def launch(tmp_path: Path, env_lines: str, shell: dict[str, str] | None = None) -> tuple[int, str, str, str]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "mac-launch.sh")
    (root / ".env").write_text(BASE_ENV + env_lines)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", STUB_DOCKER), ("curl", "#!/bin/sh\nexit 0\n")):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    # A clean environment: nothing from the shell running pytest (AWS keys, EXTRAS) leaks in.
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "STUB_LOG": str(log)}
    env.update(shell or {})
    done = subprocess.run(
        ["bash", str(root / "scripts" / "mac-launch.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr, log.read_text()


def compose_up(log: str) -> str:
    return next((line for line in log.splitlines() if " up -d --build" in line), "")


def test_the_script_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, check=False).returncode == 0


def test_the_nutrition_bearer_form_is_accepted_without_the_boto3_extra(tmp_path: Path) -> None:
    code, out, err, log = launch(
        tmp_path,
        "EXTRACTION_PROVIDER=bedrock\n"
        f"BEDROCK_MODEL={CLAUDE}\n"  # an older .env's value; BEDROCK_MODEL_ID wins
        f"AWS_BEARER_TOKEN_BEDROCK={TOKEN}\n"
        f"BEDROCK_BASE_URL={BASE_URL}\n"
        f"BEDROCK_MODEL_ID={GEMMA}\n",
    )
    assert code == 0, err
    assert f"extraction: Bedrock (OpenAI-compatible endpoint) {GEMMA} at {BASE_URL}" in out
    assert TOKEN not in out + err
    assert compose_up(log).endswith("EXTRAS=<unset>")


def test_the_bearer_form_can_come_from_the_shell(tmp_path: Path) -> None:
    code, out, err, log = launch(
        tmp_path,
        "EXTRACTION_PROVIDER=bedrock\n",
        shell={"AWS_BEARER_TOKEN_BEDROCK": TOKEN, "BEDROCK_BASE_URL": BASE_URL, "BEDROCK_MODEL_ID": GEMMA},
    )
    assert code == 0, err
    assert f"(OpenAI-compatible endpoint) {GEMMA}" in out
    assert compose_up(log)


def test_bedrock_openai_is_the_bearer_form_by_name(tmp_path: Path) -> None:
    code, out, err, _ = launch(
        tmp_path,
        f"EXTRACTION_PROVIDER=bedrock_openai\nAWS_BEARER_TOKEN_BEDROCK={TOKEN}\n"
        f"BEDROCK_BASE_URL={BASE_URL}\nBEDROCK_MODEL={GEMMA}\n",
    )
    assert code == 0, err
    assert f"(OpenAI-compatible endpoint) {GEMMA}" in out  # BEDROCK_MODEL is enough on its own


def test_the_access_key_form_still_builds_the_bedrock_extra(tmp_path: Path) -> None:
    code, out, err, log = launch(
        tmp_path,
        f"EXTRACTION_PROVIDER=bedrock\nBEDROCK_MODEL={CLAUDE}\n"
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLE\nAWS_SECRET_ACCESS_KEY=secret-example\n",
    )
    assert code == 0, err
    assert f"extraction: Bedrock (Converse API) {CLAUDE} in ap-south-1" in out
    assert compose_up(log).endswith("EXTRAS=[bedrock]")


def test_half_a_bearer_pair_next_to_access_keys_says_which_path_runs(tmp_path: Path) -> None:
    code, out, err, log = launch(
        tmp_path,
        f"EXTRACTION_PROVIDER=bedrock\nBEDROCK_MODEL={CLAUDE}\nBEDROCK_BASE_URL={BASE_URL}\n"
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLE\nAWS_SECRET_ACCESS_KEY=secret-example\n",
    )
    assert code == 0, err
    assert "AWS_BEARER_TOKEN_BEDROCK is empty" in out + err
    assert "(Converse API)" in out
    assert compose_up(log).endswith("EXTRAS=[bedrock]")


@pytest.mark.parametrize(
    ("env_lines", "expected"),
    [
        # Neither credential: both ways are named.
        (
            f"EXTRACTION_PROVIDER=bedrock\nBEDROCK_MODEL_ID={GEMMA}\n",
            ["AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID"],
        ),
        # Half the bearer pair and no access keys: the missing half is named.
        (
            f"EXTRACTION_PROVIDER=bedrock\nBEDROCK_MODEL_ID={GEMMA}\nAWS_BEARER_TOKEN_BEDROCK={TOKEN}\n",
            ["BEDROCK_BASE_URL"],
        ),
        # An access key without its secret.
        (
            f"EXTRACTION_PROVIDER=bedrock\nBEDROCK_MODEL={CLAUDE}\nAWS_ACCESS_KEY_ID=AKIAEXAMPLE\n",
            ["AWS_SECRET_ACCESS_KEY"],
        ),
        # bedrock_openai with only access keys: it needs the bearer pair.
        (
            f"EXTRACTION_PROVIDER=bedrock_openai\nBEDROCK_MODEL_ID={GEMMA}\n"
            "AWS_ACCESS_KEY_ID=AKIAEXAMPLE\nAWS_SECRET_ACCESS_KEY=secret-example\n",
            ["AWS_BEARER_TOKEN_BEDROCK", "BEDROCK_BASE_URL"],
        ),
        # A credential but no model under either name.
        (
            f"EXTRACTION_PROVIDER=bedrock\nAWS_BEARER_TOKEN_BEDROCK={TOKEN}\nBEDROCK_BASE_URL={BASE_URL}\n",
            ["BEDROCK_MODEL_ID"],
        ),
    ],
)
def test_what_is_missing_is_named_and_nothing_starts(
    tmp_path: Path, env_lines: str, expected: list[str]
) -> None:
    code, out, err, log = launch(tmp_path, env_lines)
    assert code == 1
    for name in expected:
        assert name in err
    assert TOKEN not in out + err
    assert not compose_up(log)
