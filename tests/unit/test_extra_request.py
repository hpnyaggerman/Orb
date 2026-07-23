"""
Per-model arbitrary request additions.

``extra_headers`` / ``extra_body`` live on the ``model_configs`` row next to
``reasoning_effort_param`` / ``reasoning_effort_value``, which do the same job
for reasoning only. Four seams:
  * the parsers turn stored text into a header dict / body dict, ignoring
    anything malformed rather than raising on a gameplay path;
  * ``ModelConfigUpdate`` rejects malformed input at save time, so the parsers'
    tolerance only ever covers hand-edited or pre-validation rows;
  * ``LLMClient`` merges both last, so an explicit setting beats what Orb built;
  * ``client_from_settings`` / ``agent_client_from_settings`` thread the
    get_settings() overlay keys through, agent falling back to the writer's.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.schemas import ModelConfigUpdate
from backend.inference import LLMClient, agent_client_from_settings, client_from_settings
from backend.inference.client import parse_extra_headers, parse_extra_body


# ── parsers ───────────────────────────────────────────────────────────────────


def test_headers_parse_lines_and_skip_noise():
    text = "X-Provider: deepinfra\n\n# a comment\nX-Billing-Mode: paygo"
    assert parse_extra_headers(text) == {"X-Provider": "deepinfra", "X-Billing-Mode": "paygo"}


def test_headers_keep_colons_in_the_value():
    # Only the first colon separates; a URL value must survive intact.
    assert parse_extra_headers("X-Ref: https://example.com:8443/x") == {"X-Ref": "https://example.com:8443/x"}


def test_headers_drop_malformed_lines_without_raising():
    # A gameplay path never dies over a parser-level issue: keep the good line.
    assert parse_extra_headers("X-Ok: 1\nno colon here\nBad Name: v") == {"X-Ok": "1"}


def test_headers_empty_input():
    assert parse_extra_headers("") == {}
    assert parse_extra_headers("   \n\n") == {}


def test_body_parses_object_only():
    assert parse_extra_body('{"provider": {"only": ["x"]}, "seed": 7}') == {"provider": {"only": ["x"]}, "seed": 7}
    assert parse_extra_body("[1, 2]") == {}  # not an object: nothing to merge
    assert parse_extra_body("{oops") == {}
    assert parse_extra_body("") == {}


# ── save-time validation ──────────────────────────────────────────────────────


def test_update_accepts_well_formed():
    assert ModelConfigUpdate(extra_headers="X-Provider: deepinfra").extra_headers == "X-Provider: deepinfra"
    assert ModelConfigUpdate(extra_body='{"seed": 1}').extra_body == '{"seed": 1}'
    assert ModelConfigUpdate(extra_headers="  ").extra_headers == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"extra_headers": "X-Provider deepinfra"},  # no colon
        {"extra_headers": "Bad Name: v"},  # whitespace in the name
        {"extra_body": "[1,2]"},  # not an object
        {"extra_body": "{nope"},  # not JSON
    ],
)
def test_update_rejects_malformed(payload):
    with pytest.raises(ValidationError):
        ModelConfigUpdate(**payload)


# ── client merge ──────────────────────────────────────────────────────────────


def test_client_defaults_are_empty():
    c = LLMClient("http://localhost:9999")
    assert c.extra_headers == {}
    assert c.extra_body == {}
    assert c._headers() == {}


def test_headers_merge_over_authorization():
    c = LLMClient("http://x", api_key="sk-1", extra_headers="X-Provider: deepinfra")
    assert c._headers() == {"Authorization": "Bearer sk-1", "X-Provider": "deepinfra"}


def test_headers_may_replace_authorization():
    # Deliberate: a gateway wanting a different auth scheme is exactly the kind
    # of thing an escape hatch exists for.
    c = LLMClient("http://x", api_key="sk-1", extra_headers="Authorization: Custom xyz")
    assert c._headers() == {"Authorization": "Custom xyz"}


# ── settings threading ────────────────────────────────────────────────────────


def test_agent_falls_back_to_writer_values():
    settings = {
        "endpoint_url": "http://x",
        "model_name": "m",
        "extra_headers": "X-Provider: deepinfra",
        "extra_body": '{"seed": 7}',
    }
    for build in (client_from_settings, agent_client_from_settings):
        c = build(settings)
        assert c.extra_headers == {"X-Provider": "deepinfra"}
        assert c.extra_body == {"seed": 7}


def test_agent_overrides_writer_values():
    settings = {
        "endpoint_url": "http://x",
        "model_name": "m",
        "extra_headers": "X-Provider: writerprov",
        "agent_extra_headers": "X-Provider: agentprov",
        "extra_body": '{"seed": 1}',
        "agent_extra_body": '{"seed": 2}',
    }
    assert client_from_settings(settings).extra_headers == {"X-Provider": "writerprov"}
    assert agent_client_from_settings(settings).extra_headers == {"X-Provider": "agentprov"}
    assert agent_client_from_settings(settings).extra_body == {"seed": 2}
