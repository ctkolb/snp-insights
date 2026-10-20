# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Minimal OpenAI-compatible chat client.

Works with any endpoint speaking OpenAI's /chat/completions: OpenRouter, Ollama
(local), and others. No third-party dependencies.
"""
import json
import os
import urllib.request

DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    # 127.0.0.1, not "localhost": Ollama binds IPv4 only and macOS may resolve
    # localhost to ::1 first.
    "ollama": "http://127.0.0.1:11434/v1",
}

# Provider preferences that keep OpenRouter traffic off providers that retain
# data. Applied only to the openrouter endpoint.
OPENROUTER_PRIVATE_PROVIDER = {"data_collection": "deny", "zdr": True}


def resolve_endpoint(endpoint, base_url=None):
    """Return (base_url, api_key, provider, extra_headers)."""
    if endpoint == "ollama":
        base = base_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_BASE_URLS["ollama"]
        return base, None, None, {}
    if endpoint == "openrouter":
        base = base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URLS["openrouter"]
        key = os.environ.get("OPENROUTER_API_KEY")
        headers = {}
        if os.environ.get("OPENROUTER_REFERER"):
            headers["HTTP-Referer"] = os.environ["OPENROUTER_REFERER"]
        if os.environ.get("OPENROUTER_TITLE"):
            headers["X-Title"] = os.environ["OPENROUTER_TITLE"]
        return base, key, dict(OPENROUTER_PRIVATE_PROVIDER), headers
    base = base_url or os.environ.get("OPENAI_BASE_URL")
    return base, os.environ.get("OPENAI_API_KEY"), None, {}


def chat(base_url, api_key, model, messages, temperature=0.0,
         response_format=None, provider=None, extra_headers=None,
         seed=None, timeout=180):
    body = {"model": model, "messages": messages, "temperature": temperature}
    if response_format:
        body["response_format"] = response_format
    if provider:
        body["provider"] = provider
    if seed is not None:
        body["seed"] = seed
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return payload["choices"][0]["message"]["content"]
