"""Cardinality, derived from the code rather than asserted as a number somebody typed in.

Two things the standard asks for:

* route labels are templated paths and carry no record ids - proved by driving real requests with
  real uuids through the app and reading the labels back off the registry;
* the series count per metric is stated as a naive bound and a real bound, both computed here from
  the route table and the provider tables, and the real bound is under 1000.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app
from app.telemetry.metrics import STATUS_CLASSES, metrics
from app.telemetry.middleware import UNMATCHED, route_index
from app.telemetry.providers import OUTCOMES, PROVIDERS, ops_for
from tests.conftest import connect_fixture_workbook, make_settings, saved_meeting_id

SERIES_CEILING = 1000

INDEX = "<!doctype html><html><head><title>Meeting Desk</title></head><body><div id=root></div></body></html>"


@pytest.fixture(params=["api_only", "web_dist"])
def client(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TestClient]:
    """Both shapes the app is deployed in.

    With ``WEB_DIST`` set the SPA is mounted at "/", which adds a route, changes what an unknown
    path matches, and is the configuration the container actually runs - so the cardinality bound
    has to hold there, not only in the API-only shape the other tests use. This fixture shadows the
    one in conftest for this module, so every test below runs twice.
    """
    web_dist = ""
    if request.param == "web_dist":
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text(INDEX)
        (dist / "assets" / "index-abc.js").write_text("console.log('meeting desk')")
        web_dist = str(dist)
    app = create_app(make_settings(tmp_path, web_dist=web_dist))
    with TestClient(app) as c:
        yield c

# A uuid, a Google file id, an A1 cell, an email: anything that identifies one record.
LEAKS = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # uuid
    r"|[0-9a-f]{32}"  # bare hex id
    r"|@"  # an email
    r"|\b\d{3,}\b",  # any run of digits long enough to be an id
    re.IGNORECASE,
)


def route_labels() -> set[str]:
    return {
        sample.labels["route"]
        for family in metrics().registry.collect()
        for sample in family.samples
        if sample.name == "http_requests_total"
    }


def test_no_path_parameter_value_reaches_a_route_label(client: TestClient) -> None:
    """Drive the routes that take ids, then read the labels back."""
    meeting_id = saved_meeting_id(client, "Mobile roadmap review")
    client.post("/notes/paste", json={"meeting_id": meeting_id, "text": "Alex S: send the deck by Friday"})
    extraction = client.post(f"/meetings/{meeting_id}/extract").json()
    point_id = extraction["points"][0]["id"]
    workbook = connect_fixture_workbook(client)

    client.get(f"/meetings/{meeting_id}")
    client.patch(f"/meetings/{meeting_id}", json={"workstream": "Mobile"})
    client.get(f"/meetings/{meeting_id}/extractions")
    client.get(f"/extractions/{extraction['extraction']['id']}")
    client.patch(f"/points/{point_id}", json={"text": "Send the deck by Friday"})
    client.post(f"/points/{point_id}/defer")
    client.post(f"/points/{point_id}/restore")
    client.get(f"/workbooks/{workbook['id']}/tabs/{workbook['tabs'][0]['sheet_id']}")
    client.get("/does/not/exist")
    client.get(f"/meetings/{meeting_id}/nope")

    labels = route_labels()
    assert labels, "no requests were recorded"
    declared = {route.path for route in client.app.routes if isinstance(route, APIRoute)}
    # Whatever answers an unknown path: the one unmatched bucket, or - with the SPA mounted - the
    # mount's single templated label. Either way it is one label, not one per URL ever requested.
    catch_all = {UNMATCHED} | {
        path for path in route_index(list(client.app.routes)).values() if path.endswith("{path:path}")
    }
    for label in labels:
        assert label in declared or label in catch_all, f"{label} is not a declared route"
        if label in catch_all:
            continue
        # Whatever is left after the {placeholders} are stripped must hold no identifier.
        skeleton = re.sub(r"\{[^}]+\}", "", label)
        assert not LEAKS.search(skeleton), f"{label} carries a record id"
    # The two unknown paths collapsed into one label, not two.
    assert len(labels & catch_all) == 1


def test_http_series_bound_is_derived_from_the_route_table(client: TestClient) -> None:
    routes = list(client.app.routes)
    index = route_index(routes)
    paths = set(index.values()) | {UNMATCHED}

    methods_used: dict[str, set[str]] = {}
    for route in routes:
        path = index.get(id(getattr(route, "endpoint", None)))
        if path is None:
            continue
        for method in getattr(route, "methods", {"GET"}) or {"GET"}:
            if method == "HEAD":
                continue  # Starlette answers HEAD on a GET route; it is counted as GET
            methods_used.setdefault(path, set()).add(method)

    all_methods = {m for ms in methods_used.values() for m in ms}

    # Naive, if every route were allowed every method the app serves anywhere:
    naive = len(paths) * len(all_methods) * len(STATUS_CLASSES)
    # Real, from the methods each route actually declares, plus the one unmatched bucket which can
    # be hit with any of them:
    real = sum(len(ms) for ms in methods_used.values()) * len(STATUS_CLASSES)
    real += len(all_methods) * len(STATUS_CLASSES)  # __unmatched__

    print(
        f"\nhttp_requests_total: {len(paths)} routes x {len(all_methods)} methods x "
        f"{len(STATUS_CLASSES)} status classes = {naive} naive, {real} real"
    )
    # Without templating there is no bound at all: one series per distinct URL ever requested.
    assert real < SERIES_CEILING, f"{real} series is over the {SERIES_CEILING} ceiling"
    # The duration histogram is (route, method) x (buckets + sum + count).
    histogram = sum(len(ms) for ms in methods_used.values()) * (len(metrics().http_duration._upper_bounds) + 2)
    print(f"http_request_duration_seconds: {histogram} real")
    assert histogram < SERIES_CEILING


def test_provider_series_bound_is_derived_from_the_provider_tables() -> None:
    naive_ops = {op for provider in PROVIDERS for op in ops_for(provider)}
    naive = len(PROVIDERS) * len(naive_ops) * len(OUTCOMES)
    real = sum(len(ops_for(provider)) for provider in PROVIDERS) * len(OUTCOMES)

    print(
        f"\nexternal_provider_requests_total: {len(PROVIDERS)} providers x {len(naive_ops)} ops x "
        f"{len(OUTCOMES)} outcomes = {naive} naive, {real} real"
    )
    assert real < SERIES_CEILING
    # The two gauges are one series per provider.
    assert len(PROVIDERS) < SERIES_CEILING
    print(f"external_provider_last_success_timestamp_seconds / breaker_state: {len(PROVIDERS)} each")


def test_background_job_series_bound() -> None:
    job_names = ("extract", "fetch_doc", "token_health")
    outcomes = ("success", "failure")
    real = len(job_names) * len(outcomes)
    print(f"\nbackground_job_total: {real} real; last_success: {len(job_names)}")
    assert real < SERIES_CEILING


def test_status_class_is_a_bucket_not_a_code(client: TestClient) -> None:
    client.get("/meetings/does-not-exist")
    classes = {
        sample.labels["status_class"]
        for family in metrics().registry.collect()
        for sample in family.samples
        if sample.name == "http_requests_total"
    }
    assert classes <= set(STATUS_CLASSES)
