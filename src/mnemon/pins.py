"""Vendored upstream pins: the chat template and tokenizer Strata renders with.

A pin lives in ``mnemon/pins_data/<name>/`` (inside the package, so it ships in the
wheel) as ``chat_template.jinja``, ``tokenizer.json`` and ``PIN.json``. ``PIN.json``
records the build it was taken from, each file's SHA-256, the tokenizer revision and
Strata's message preprocessing rules. Every file is verified on load; the manifest
itself is checked against ``KNOWN_PINS``, so changing a pin is a code change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_PIN = "strata-0.1.48"

# sha256 of each known pin's PIN.json.
KNOWN_PINS = {
    "strata-0.1.48": "cf3b5a426570e0220450ec09626c24b1849cd6349414430d77961bdd76cef096",
}

_TEMPLATE = "chat_template.jinja"
_TOKENIZER = "tokenizer.json"
_MANIFEST = "PIN.json"


class PinError(Exception):
    """A pin file is missing or does not match its recorded hash."""


@dataclass(frozen=True)
class Pin:
    name: str
    # name plus a prefix of the manifest hash; keys anything derived from the pin.
    id: str
    build_info: str
    template_sha256: str
    tokenizer_sha256: str
    tokenizer_revision: str
    chat_template: str = field(repr=False)
    tokenizer_json: bytes = field(repr=False)
    manifest: dict[str, Any] = field(repr=False)


def pin_dir(name: str = DEFAULT_PIN) -> Path:
    return Path(str(resources.files("mnemon") / "pins_data" / name))


def _read(directory: Path, filename: str) -> bytes:
    try:
        return (directory / filename).read_bytes()
    except OSError as exc:
        raise PinError(f"pin file {filename} unreadable in {directory}: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(directory: Path | str | None = None) -> Pin:
    """Load and verify a pin directory (default: the vendored ``DEFAULT_PIN``)."""
    directory = pin_dir() if directory is None else Path(directory)
    raw_manifest = _read(directory, _MANIFEST)
    manifest_sha = _sha256(raw_manifest)
    try:
        manifest = json.loads(raw_manifest)
        name = manifest["pin"]
        files = manifest["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PinError(f"pin file {_MANIFEST} malformed: {exc}") from exc
    if KNOWN_PINS.get(name) != manifest_sha:
        raise PinError(f"pin file {_MANIFEST} for {name!r} has unknown sha256 {manifest_sha}")
    contents: dict[str, bytes] = {}
    for filename in (_TEMPLATE, _TOKENIZER):
        data = _read(directory, filename)
        expected = files[filename]["sha256"]
        actual = _sha256(data)
        if actual != expected:
            raise PinError(f"pin file {filename} sha256 {actual} != pinned {expected}")
        contents[filename] = data
    return Pin(
        name=name,
        id=f"{name}@{manifest_sha[:12]}",
        build_info=manifest["build_info"],
        template_sha256=files[_TEMPLATE]["sha256"],
        tokenizer_sha256=files[_TOKENIZER]["sha256"],
        tokenizer_revision=files[_TOKENIZER]["revision"],
        chat_template=contents[_TEMPLATE].decode("utf-8"),
        tokenizer_json=contents[_TOKENIZER],
        manifest=manifest,
    )
