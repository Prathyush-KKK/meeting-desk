"""The alert rules are a consumer of these metrics, and their runbooks point at real event tokens.

The last two items of the PR checklist in docs/TELEMETRY.md:

* "A consumer exists: at least one alert rule reads these metrics" - asserted per rule;
* "Any runbook string that quotes log content uses event tokens, and a test asserts those tokens
  exist in the emitting code" - asserted token by token, against ``app/telemetry/events.py`` and
  against the call sites.

The chart is read as text rather than rendered: the templates are Go templates, `helm` is not a
test dependency, and what is being checked (the rule bodies, the label names, the tokens) is
literal in the file. ``make ci`` runs ``helm lint`` and ``helm template`` for the rest.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.telemetry.events import EVENTS
from app.telemetry.metrics import BUILD_INFO_METRIC, REQUIRED_METRIC_NAMES

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "deploy" / "helm" / "meeting-desk"
RULES = CHART / "templates" / "prometheusrule.yaml"
APP = Path(__file__).resolve().parents[1] / "app"

# The shape docs/TELEMETRY.md prescribes: grep '"event":"(a|b)"'
EVENT_GREP = re.compile(r'"event":"\(?([a-z_|]+)\)?"')


def rule_blocks(text: str) -> list[tuple[str, str]]:
    """(alert name, block text) for every `- alert:` in the file."""
    parts = re.split(r"\n\s*- alert: ", text)
    blocks: list[tuple[str, str]] = []
    for part in parts[1:]:
        name = part.split("\n", 1)[0].strip()
        blocks.append((name, part))
    return blocks


def tokens_in(text: str) -> set[str]:
    found: set[str] = set()
    for match in EVENT_GREP.finditer(text):
        found.update(t for t in match.group(1).split("|") if t)
    return found


def test_the_chart_and_its_rules_are_there() -> None:
    assert (CHART / "Chart.yaml").is_file()
    assert (CHART / "values.yaml").is_file()
    assert (CHART / "values-production.example.yaml").is_file()
    assert RULES.is_file()


def test_every_event_token_a_rule_quotes_exists_in_the_code() -> None:
    quoted = tokens_in(RULES.read_text())
    assert quoted, "no remediation quotes an event token"
    unknown = quoted - EVENTS
    assert not unknown, f"the rules grep for tokens nothing emits: {sorted(unknown)}"


def test_every_token_a_rule_quotes_is_actually_emitted() -> None:
    """In ``events.py`` is not enough: the constant has to be used at a call site."""
    quoted = tokens_in(RULES.read_text())
    constants = _constant_names()
    sources = {path: path.read_text() for path in APP.rglob("*.py") if path.name != "events.py"}
    for token in sorted(quoted):
        name = constants[token]
        emitted = any(re.search(rf"\b(events\.)?{name}\b", text) for text in sources.values())
        assert emitted, f"{token} ({name}) is declared but never logged"


def test_every_rule_reads_one_of_the_six_metrics() -> None:
    text = RULES.read_text()
    known = {*REQUIRED_METRIC_NAMES, BUILD_INFO_METRIC, "http_request_duration_seconds_bucket"}
    for name, block in rule_blocks(text):
        expression = block.split("for:")[0]
        assert any(metric in expression for metric in known), f"{name} reads no standard metric"


def test_every_rule_carries_service_and_severity_labels_and_a_remediation() -> None:
    for name, block in rule_blocks(RULES.read_text()):
        assert "\n          labels:" in block, f"{name} has no labels"
        assert re.search(r"\n\s+service: ", block), f"{name} has no service label"
        assert re.search(r"\n\s+severity: (critical|warning|info)", block), f"{name} has no severity"
        assert re.search(r"\n\s+remediation: ", block), f"{name} has no remediation annotation"
        assert re.search(r'"event":"', block), f"{name}'s remediation does not quote an event token"


def test_the_last_success_rules_use_max_over_time_absent_and_min_by_provider() -> None:
    text = RULES.read_text()
    stale = next(block for name, block in rule_blocks(text) if "LastSuccessStale" in name)
    assert "max_over_time(" in stale
    assert "min by (provider)" in stale
    absent = next(block for name, block in rule_blocks(text) if "Absent" in name)
    assert "absent(" in absent


def test_the_five_rules_the_spec_names_are_present() -> None:
    names = {name for name, _ in rule_blocks(RULES.read_text())}
    for wanted in (
        "MeetingDeskProviderLastSuccessStale",  # provider last-success stale
        "MeetingDeskExtractionFailureRate",  # extraction failure rate
        "MeetingDeskSheetsErrorRate",  # Sheets 4xx / 5xx
        "MeetingDeskTransferConflictRate",  # transfer 409 rate
        "MeetingDeskOAuthRefreshFailing",  # OAuth refresh failures
    ):
        assert wanted in names, f"{wanted} is missing from the PrometheusRule"


def test_the_service_and_the_servicemonitor_agree_on_the_port_name() -> None:
    service = (CHART / "templates" / "service.yaml").read_text()
    monitor = (CHART / "templates" / "servicemonitor.yaml").read_text()
    assert "- name: metrics" in service
    assert "targetPort: metrics" in service
    assert "port: metrics" in monitor
    assert "targetPort: {{ .Values.containerPorts.metrics }}" not in monitor


def test_the_ingress_never_points_at_the_metrics_port() -> None:
    ingress = (CHART / "templates" / "ingress.yaml").read_text()
    assert "name: http" in ingress
    assert "metrics" not in ingress.split("spec:")[1]


def test_no_secret_value_is_in_the_chart() -> None:
    """Only secret-store paths. A literal key here would be a leak in git history."""
    for path in CHART.rglob("*.yaml"):
        text = path.read_text()
        assert "BEGIN PRIVATE KEY" not in text
        assert "1//" not in text  # a Google refresh token
        for line in text.splitlines():
            if re.search(r"(SECRET|TOKEN_KEY|CLIENT_SECRET|PASSWORD):\s*\S", line):
                value = line.split(":", 1)[1].strip().strip('"')
                assert value in ("", "{{", "''") or value.startswith("{{"), f"{path.name}: {line}"


def _constant_names() -> dict[str, str]:
    """token -> the constant's name in events.py."""
    source = (APP / "telemetry" / "events.py").read_text()
    out: dict[str, str] = {}
    for match in re.finditer(r'^([A-Z_]+) = "([a-z_]+)"$', source, re.MULTILINE):
        out[match.group(2)] = match.group(1)
    return out
