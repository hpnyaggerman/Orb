"""
Proxy setting contracts: LLMClient normalizes the stored value and the
SettingsUpdate schema gates the scheme at save time.

The value passed to httpx is ``LLMClient.proxy``; httpx accepts http/https/socks5
URLs (socks5 via the socksio extra) and rejects an empty string, so the client
turns the settings default ("" = no proxy) into None for a direct connection.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.schemas import SettingsUpdate
from backend.inference import LLMClient


def test_llmclient_proxy_default_is_none():
    assert LLMClient("http://localhost:9999").proxy is None


def test_llmclient_empty_proxy_normalizes_to_none():
    # The settings default is "" (no proxy); httpx rejects "" as a URL, so it
    # must reach httpx as None (direct connection).
    assert LLMClient("http://localhost:9999", proxy="").proxy is None


def test_llmclient_preserves_real_proxy():
    c = LLMClient("http://localhost:9999", proxy="socks5://127.0.0.1:1080")
    assert c.proxy == "socks5://127.0.0.1:1080"


@pytest.mark.parametrize(
    "url",
    ["http://proxy:8080", "https://proxy:8443", "socks5://127.0.0.1:1080"],
)
def test_settings_update_accepts_supported_schemes(url):
    assert SettingsUpdate(llm_proxy=url).llm_proxy == url


def test_settings_update_blank_proxy_becomes_empty():
    assert SettingsUpdate(llm_proxy="   ").llm_proxy == ""


def test_settings_update_trims_proxy():
    assert SettingsUpdate(llm_proxy="  socks5://h:1  ").llm_proxy == "socks5://h:1"


@pytest.mark.parametrize("url", ["socks5h://h:1", "socks4://h:1", "ftp://h:1", "not-a-url"])
def test_settings_update_rejects_unsupported_schemes(url):
    # socks5h/socks4 are rejected too -- httpx 0.27 does not accept them, so the
    # allowlist must match what httpx can actually build.
    with pytest.raises(ValidationError):
        SettingsUpdate(llm_proxy=url)
