"""Move optional wheel contents out of the frozen app; pin their upstream downloads."""
from importlib.metadata import distribution
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def dependencies(requirements):
    found, visited = {}, set()
    pending = [Requirement(value) for value in requirements]
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        identity = name, tuple(sorted(requirement.extras))
        if identity in visited:
            continue
        visited.add(identity)
        package = distribution(name)
        found[name] = package
        for value in package.requires or ():
            child = Requirement(value)
            if child.marker is None or any(child.marker.evaluate({"extra": extra})
                                           for extra in ("", *requirement.extras)):
                pending.append(child)
    return found


def prepare(root):
    import tomllib
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    core = dependencies(["setuptools", *(value for value in project["dependencies"]
                        if Requirement(value).marker is None or Requirement(value).marker.evaluate())])
    groups = {"stanza": ["stanza", "torch"]}
    if sys.platform == "win32":
        groups["paddle"] = ["paddleocr", "paddlex[ocr-core]", "paddlepaddle"]
    optional = {key: {name: package for name, package in dependencies(values).items() if name not in core}
                for key, values in groups.items()}
    packages = {name: package for group in optional.values() for name, package in group.items()}
    folder = root / "build" / "optional-runtimes"
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / "wheels.json"
    resolved = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    previous = {canonicalize_name(item["metadata"]["name"]): item["metadata"]["version"]
                for item in resolved.get("install", ())}
    environment = resolved.get("environment", {})
    if (previous != {name: package.version for name, package in packages.items()}
            or environment.get("sys_platform") != sys.platform
            or environment.get("platform_machine", "").lower() != platform.machine().lower()
            or environment.get("python_version") != f"{sys.version_info.major}.{sys.version_info.minor}"):
        subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--no-deps",
                        "--only-binary=:all:", "--disable-pip-version-check", "--report", str(report),
                        "--extra-index-url", "https://download.pytorch.org/whl/cpu",
                        *(f"{name}=={package.version}" for name, package in sorted(packages.items()))], check=True)
    wheels = {}
    for item in json.loads(report.read_text(encoding="utf-8"))["install"]:
        download = item["download_info"]
        name = canonicalize_name(item["metadata"]["name"])
        if not download["url"].split("?", 1)[0].endswith(".whl"):
            raise ValueError("Optional runtimes require binary wheels")
        digest = download["archive_info"].get("hashes", {}).get("sha256")
        if digest is None:
            with urlopen(download["url"], timeout=60) as response:
                digest = hashlib.file_digest(response, "sha256").hexdigest()
        wheels[name] = {"name": name, "version": item["metadata"]["version"], "url": download["url"], "sha256": digest}
    manifest = {"schema": 1, "platform": f"{sys.platform}-{platform.machine().lower()}",
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "features": {key: [wheels[name] for name in sorted(group)] for key, group in optional.items()}}
    destination = folder / "runtimes.json"
    destination.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    # File ownership avoids accidentally removing shared NumPy/OpenCV dependencies.
    owned = lambda package: {os.path.normcase(str(package.locate_file(path).resolve()))
                             for path in package.files or () if ".." not in path.parts}
    external = set().union(*(owned(package) for package in packages.values()))
    external.difference_update(set().union(*(owned(package) for package in core.values())))
    return destination, external


def strip(analysis, external):
    def keep(entry):
        return os.path.normcase(str(Path(entry[1]).resolve())) not in external
    # Analyze first so optional imports still contribute required standard-library modules.
    analysis.pure = [entry for entry in analysis.pure if keep(entry)]
    analysis.binaries = [entry for entry in analysis.binaries if keep(entry)]
    analysis.datas = [entry for entry in analysis.datas if keep(entry)]
