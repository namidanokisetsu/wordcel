"""Validation and discovery for managed and user selected GGUF models.

The built in models remain pinned in :mod:`wordcel.translation_catalog`.  This
module only adds the small, identity based contract used by imported models;
it deliberately does not probe the filesystem while validating settings.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from wordcel.translation_catalog import MODELS


CUSTOM_PROFILE_PREFIX = "gguf:"
CUSTOM_PROFILE_RE = re.compile(r"^gguf:[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_QUANTIZATION_RE = re.compile(r"(?i)(?:^|[-_.])((?:(?:Q|IQ|BF|F)[0-9][A-Z0-9_]*(?:_[A-Z0-9]+)?))")
_SHARD_RE = re.compile(r"(?i)-[0-9]{5}-of-[0-9]{5}\.gguf$")


def is_custom_profile(profile: object) -> bool:
    return isinstance(profile, str) and CUSTOM_PROFILE_RE.fullmatch(profile) is not None


def profile_id(digest: str) -> str:
    digest = _digest(digest)
    return CUSTOM_PROFILE_PREFIX + digest


def model_identity(spec: object) -> str:
    """Return the stable profile id for a descriptor or digest."""
    if isinstance(spec, dict):
        spec = spec.get("sha256")
    return profile_id(spec)


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value.lower()) is None:
        raise ValueError("A model SHA-256 digest is required.")
    return value.lower()


def _safe_source_file(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Invalid GGUF source filename.")
    from wordcel.optional_runtimes import safe_member
    try:
        path = safe_member(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid GGUF source filename.") from None
    if not value.lower().endswith(".gguf"):
        raise ValueError("Invalid GGUF source filename.")
    return path.as_posix()


def _safe_repo_id(value: object) -> str:
    if not isinstance(value, str) or _REPO_RE.fullmatch(value) is None:
        raise ValueError("Invalid Hugging Face repository id.")
    return value


def _text(value: object, field: str, *, default: str = "", maximum: int = 200) -> str:
    if value is None and default:
        value = default
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid custom model {field}.")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid custom model {field}.")
    return value.strip()


def validate_custom_spec(profile: str | None, spec: object, *, require_source: bool = True) -> dict[str, Any]:
    """Return a canonical custom descriptor or reject untrusted metadata.

    ``profile`` is supplied separately because registry keys are part of the
    model identity.  A local descriptor has ``source == "local"`` and does
    not need a publisher revision; a Hub descriptor has a full commit SHA.
    """
    if profile is not None and not is_custom_profile(profile):
        raise ValueError("Invalid custom translation model identity.")
    if not isinstance(spec, dict):
        raise ValueError("Invalid custom translation model metadata.")
    digest = _digest(spec.get("sha256"))
    identity = profile_id(digest)
    if profile is not None and profile != identity:
        raise ValueError("Custom translation model identity does not match its SHA-256.")
    if "profile" in spec and spec["profile"] != identity:
        raise ValueError("Custom translation model identity does not match its SHA-256.")
    size = spec.get("size")
    if type(size) is not int or size <= 0:
        raise ValueError("Invalid custom translation model size.")
    filename = spec.get("file", f"custom-{digest}.gguf")
    if filename != f"custom-{digest}.gguf":
        raise ValueError("Invalid custom translation model filename.")
    path = spec.get("path", "models/" + filename)
    if path != "models/" + filename:
        raise ValueError("Invalid custom translation model path.")
    source = spec.get("source", "hf")
    if source not in ("hf", "local"):
        raise ValueError("Invalid custom translation model source.")
    if require_source and source == "hf":
        repo_id = _safe_repo_id(spec.get("repo_id"))
        source_file = _safe_source_file(spec.get("source_file"))
        revision = spec.get("revision")
        if not isinstance(revision, str) or _REVISION_RE.fullmatch(revision.lower()) is None:
            raise ValueError("Custom Hugging Face model revision must be a commit SHA.")
    else:
        repo_id = spec.get("repo_id", "")
        source_file = spec.get("source_file", filename)
        revision = spec.get("revision", "")
        if repo_id:
            repo_id = _safe_repo_id(repo_id)
        source_file = _safe_source_file(source_file)
        if revision and (not isinstance(revision, str) or len(revision) > 128):
            raise ValueError("Invalid custom model revision.")
    name = _text(spec.get("name"), "name", default=filename, maximum=200)
    label = _text(spec.get("label"), "label", default=name, maximum=200)
    quantization = spec.get("quantization", "unknown")
    quantization = _text(quantization, "quantization", default="unknown", maximum=64)
    memory = spec.get("memory", size + 2 * 1024**3)
    if type(memory) is not int or memory <= 0:
        raise ValueError("Invalid custom model memory estimate.")
    result = {
        "profile": identity,
        "source": source,
        "file": filename,
        "path": path,
        "size": size,
        "sha256": digest,
        "name": name,
        "label": label,
        "quantization": quantization,
        "memory": memory,
    }
    if repo_id:
        result["repo_id"] = repo_id
    if source_file:
        result["source_file"] = source_file
    if revision:
        result["revision"] = revision.lower() if isinstance(revision, str) and _REVISION_RE.fullmatch(revision.lower()) else revision
    if "url" in spec:
        url = spec["url"]
        if not isinstance(url, str) or len(url) > 2048 or any(ord(char) < 32 for char in url):
            raise ValueError("Invalid custom model URL.")
        result["url"] = url
    return result


def custom_models(registry: object) -> dict[str, dict[str, Any]]:
    """Validate a registry's custom model map without touching model files."""
    if not isinstance(registry, dict):
        return {}
    values = registry.get("custom_models", {})
    if values is None:
        return {}
    if not isinstance(values, dict) or len(values) > 64:
        raise ValueError("Invalid custom translation model registry.")
    result = {}
    for profile, spec in values.items():
        if not isinstance(profile, str):
            raise ValueError("Invalid custom translation model identity.")
        result[profile] = validate_custom_spec(profile, spec)
    return result


def _registry_from_directory(directory: str | Path | None) -> dict:
    if directory is None:
        from wordcel.utils.paths import paths
        directory = Path(paths.data_dir) / "translation"
    path = Path(directory) / "installation.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def model_catalog(directory: str | Path | None = None, *, registry: dict | None = None) -> dict[str, dict[str, Any]]:
    """Return built-ins plus validated custom descriptors.

    Callers that already have the installation registry can pass it to avoid a
    second read.  The result is copied so UI code cannot mutate the catalog.
    """
    result = {key: dict(value) for key, value in MODELS.items()}
    for profile, spec in custom_models(registry if registry is not None else _registry_from_directory(directory)).items():
        result[profile] = dict(spec)
    return result


def model_spec(profile: str, directory: str | Path | None = None, *, registry: dict | None = None) -> dict[str, Any] | None:
    if profile in MODELS:
        return dict(MODELS[profile])
    if not is_custom_profile(profile):
        return None
    return model_catalog(directory, registry=registry).get(profile)


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _quantization(filename: str) -> str:
    match = _QUANTIZATION_RE.search(filename)
    return match.group(1) if match else "unknown"


def _descriptor(repo_id: str, source_file: str, revision: str, size: int, digest: str) -> dict[str, Any]:
    digest = _digest(digest)
    source_file = _safe_source_file(source_file)
    if type(size) is not int or size <= 0:
        raise ValueError("Hugging Face GGUF metadata has no valid size.")
    quantization = _quantization(Path(source_file).name)
    stem = Path(source_file).stem
    name = f"{stem} {quantization}" if quantization != "unknown" else stem
    result = dict(source="hf", repo_id=_safe_repo_id(repo_id), source_file=source_file,
                  revision=revision, size=size, sha256=digest, file=f"custom-{digest}.gguf",
                  name=name, label=name, quantization=quantization,
                  memory=size + 2 * 1024**3)
    return validate_custom_spec(None, result)


def list_hub_models(repo_id: str) -> list[dict[str, Any]]:
    """List one-file GGUF choices using publisher commit/LFS metadata.

    Sharded files are skipped and metadata-incomplete complete files are
    rejected because a custom profile must identify one payload before
    installation begins.
    """
    repo_id = _safe_repo_id(repo_id)
    from huggingface_hub import HfApi
    info = HfApi().model_info(repo_id, files_metadata=True, token=False)
    revision = getattr(info, "sha", None)
    if not isinstance(revision, str) or _REVISION_RE.fullmatch(revision.lower()) is None:
        raise ValueError("Hugging Face did not provide a pinned commit revision.")
    descriptors = []
    for sibling in getattr(info, "siblings", ()) or ():
        filename = _field(sibling, "rfilename") or _field(sibling, "path")
        if (not isinstance(filename, str) or not filename.lower().endswith(".gguf") or
                _SHARD_RE.search(filename)):
            continue
        lfs = _field(sibling, "lfs", {}) or {}
        digest = _field(lfs, "sha256") or _field(sibling, "sha256")
        size = _field(sibling, "size")
        if digest is None or size is None:
            raise ValueError("Hugging Face GGUF metadata is incomplete.")
        descriptors.append(_descriptor(repo_id, filename, revision.lower(), size, digest))
    if not descriptors:
        raise ValueError("The repository has no complete GGUF model.")
    return descriptors


def resolve_hf(repo_id: str, source_file: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
    choices = list_hub_models(repo_id)
    if source_file is None:
        return choices
    source_file = _safe_source_file(source_file)
    for choice in choices:
        if choice["source_file"] == source_file:
            return choice
    raise ValueError("The selected GGUF file was not found in the pinned repository revision.")


resolve_HF = resolve_hf


def local_model(path: str | Path, cancelled=None) -> dict[str, Any]:
    """Hash a local GGUF and return an identity-stable import descriptor."""
    path = Path(path)
    if path.suffix.lower() != ".gguf" or not path.is_file():
        raise ValueError("Choose an existing GGUF model file.")
    filename = path.name
    with path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("The selected file is not a GGUF model.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            if cancelled and (cancelled.is_set() if hasattr(cancelled, "is_set") else cancelled()):
                raise InterruptedError("Translation model import cancelled.")
            digest.update(chunk)
            size += len(chunk)
    quantization = _quantization(filename)
    name = Path(filename).stem
    return validate_custom_spec(None, dict(source="local", source_file=filename, size=size,
                                           sha256=digest.hexdigest(), name=name, label=name,
                                           quantization=quantization, memory=size + 2 * 1024**3))

