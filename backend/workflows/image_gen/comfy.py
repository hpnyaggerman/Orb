"""ComfyUI HTTP client and placeholder-sentinel graph injection.

Depends only on the standard library and ``httpx``; it carries no reference to
the workflow framework so it stays independently importable and testable.

Injection is node-id-agnostic: values are written wherever a known ``{{...}}``
sentinel appears in the graph, and the output is read from whichever node is a
``SaveImage``. This keeps a user-supplied custom graph compatible as long as it
carries the same sentinels, without this module knowing any node ids.

Every failure mode of a render -- unreachable host, timeout, HTTP error, a node
erroring, malformed response, missing or empty output -- is funneled into a
single ``ComfyError`` so callers have one exception to catch.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Sentinel token -> (value key, coercion). The template carries these as whole
# string values; injection replaces them with the typed runtime value.
SENTINELS: dict[str, tuple[str, type]] = {
    "{{positive}}": ("positive", str),
    "{{negative}}": ("negative", str),
    "{{seed}}": ("seed", int),
    "{{cfg}}": ("cfg", float),
    "{{steps}}": ("steps", int),
    "{{width}}": ("width", int),
    "{{height}}": ("height", int),
}

# A graph without a positive-prompt slot cannot depict the scene, so its absence
# is a hard error; every other sentinel is optional and its graph value stands.
MANDATORY_SENTINELS: frozenset[str] = frozenset({"{{positive}}"})

_SENTINEL_SHAPE = re.compile(r"^\{\{.*\}\}$")

_TEMPLATE_PATH = Path(__file__).with_name("cg_pipeline.json")


class ComfyError(Exception):
    """Any failure to produce a rendered image from ComfyUI."""


def load_template() -> dict:
    """Load the packaged ComfyUI API-format graph template."""
    with _TEMPLATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def inject_graph(template: dict, values: dict) -> dict:
    """Return a copy of ``template`` with every sentinel replaced by its value.

    Matches sentinels by whole-value equality only, so a composed prompt that
    happens to contain a token does not trigger recursive replacement. A missing
    mandatory sentinel or a value that fails coercion raises ``ComfyError``; an
    absent optional sentinel simply leaves the graph's baked value in place.
    """
    graph = copy.deepcopy(template)
    found: set[str] = set()
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, val in list(inputs.items()):
            if not isinstance(val, str):
                continue
            if val in SENTINELS:
                field, caster = SENTINELS[val]
                try:
                    inputs[key] = caster(values[field])
                except (KeyError, TypeError, ValueError) as e:
                    raise ComfyError(f"could not resolve sentinel {val}: {e}") from e
                found.add(val)
            elif _SENTINEL_SHAPE.match(val):
                logger.warning("image_gen: graph carries an unknown sentinel %r", val)
    missing = MANDATORY_SENTINELS - found
    if missing:
        raise ComfyError(f"graph is missing required slot(s): {', '.join(sorted(missing))}")
    return graph


def _save_node_ids(graph: dict) -> list[str]:
    return [nid for nid, node in graph.items() if isinstance(node, dict) and node.get("class_type") == "SaveImage"]


def _first_image(outputs: dict, save_ids: list[str]) -> dict | None:
    """The first image record in the outputs, preferring the SaveImage nodes."""
    for nid in save_ids:
        images = (outputs.get(nid) or {}).get("images") or []
        if images:
            return images[0]
    for node_output in outputs.values():
        images = (node_output or {}).get("images") or []
        if images:
            return images[0]
    return None


async def generate_image(graph: dict, *, base_url: str, timeout: float, poll_interval: float = 0.75) -> tuple[bytes, str]:
    """Submit ``graph`` to ComfyUI, await the render, and return ``(bytes, mime)``.

    Submits to ``POST /prompt``, polls ``GET /history/{id}`` until the run
    appears, then fetches the saved image from ``GET /view``. ``timeout`` bounds
    both the per-request deadline and the overall poll loop. Raises ``ComfyError``
    on any failure.
    """
    base = base_url.rstrip("/")
    save_ids = _save_node_ids(graph)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        try:
            resp = await client.post(f"{base}/prompt", json={"prompt": graph})
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ComfyError(f"submit failed: {e}") from e

        deadline = time.monotonic() + timeout
        while True:
            try:
                resp = await client.get(f"{base}/history/{prompt_id}")
                resp.raise_for_status()
                entry = resp.json().get(prompt_id)
            except (httpx.HTTPError, ValueError) as e:
                raise ComfyError(f"history poll failed: {e}") from e
            if entry:
                if (entry.get("status") or {}).get("status_str") == "error":
                    raise ComfyError("render reported an execution error")
                image = _first_image(entry.get("outputs") or {}, save_ids)
                if image is None:
                    raise ComfyError("render produced no image output")
                try:
                    view = await client.get(
                        f"{base}/view",
                        params={
                            "filename": image.get("filename"),
                            "subfolder": image.get("subfolder", ""),
                            "type": image.get("type", "output"),
                        },
                    )
                    view.raise_for_status()
                except httpx.HTTPError as e:
                    raise ComfyError(f"image fetch failed: {e}") from e
                if not view.content:
                    raise ComfyError("fetched image was empty")
                return view.content, view.headers.get("content-type", "image/png")
            if time.monotonic() >= deadline:
                raise ComfyError("render timed out")
            await asyncio.sleep(poll_interval)
