"""Explicit publisher revision checks and staged shared dictionary replacement."""
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from wordcel import USER_AGENT
from .library import Library, import_yomitan, library_changed


@dataclass(frozen=True)
class DictionaryUpdate:
    identity: str
    title: str
    language: str
    installed: str
    available: str = ""
    url: str = ""
    status: str = "Replace from ZIP"
    source: str = ""


def publisher_url(value):
    url = urlsplit(value)
    if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
        raise ValueError("Invalid dictionary publisher URL.")
    return value


def check_update(metadata, fetch=None):
    result = DictionaryUpdate(metadata["resource_id"], metadata["title"], metadata["language"],
                              metadata.get("revision", ""), source=metadata.get("source", ""))
    from dataclasses import replace
    index_url = metadata.get("index_url", "")
    if not index_url:
        from .catalog import recommendations
        recommended = next((item for item in recommendations(metadata["language"])
                            if item.identity == metadata["resource_id"]), None)
        if recommended and "jmdict-yomitan" in recommended.url:
            index_url = recommended.url.removesuffix(".zip") + ".json"
    if not index_url:
        return result
    try:
        if fetch is None:
            def fetch(url):
                with urlopen(Request(publisher_url(url), headers={"User-Agent": USER_AGENT}), timeout=30) as response:
                    raw = response.read(256 * 1024 + 1)
                if len(raw) > 256 * 1024:
                    raise ValueError("Dictionary index is too large.")
                return json.loads(raw)
        index = fetch(publisher_url(index_url))
        revision = index.get("revision")
        if not isinstance(revision, str) or not revision or not index.get("downloadUrl"):
            return result
        if index.get("sourceLanguage", result.language) != result.language:
            raise ValueError("Publisher changed the dictionary language.")
        url = publisher_url(index["downloadUrl"])
        return replace(result, available=revision, url=url,
                       status="Up to date" if revision == result.installed else "Update available")
    except Exception as error:
        return replace(result, status=str(error))


def replace_dictionary(archive, directory, identity, progress=None, cancelled=None):
    """Publish only after validation; existing readers keep their old SQLite file."""
    library = Library(directory)
    try:
        selected = next((dict(meta) for _, meta, _ in library.packs if meta["resource_id"] == identity), None)
    finally:
        library.close()
    if selected is None:
        raise ValueError("Dictionary is no longer installed.")
    # Import publication is atomic. Matching identity selects the new revision only
    # after its complete database and media are on disk, including after a restart.
    path = import_yomitan(archive, directory, language=selected["language"], progress=progress,
                          cancelled=cancelled, resource_id=identity, source=selected.get("source", ""),
                          expected_language=selected["language"], expected_metadata=selected,
                          origin=selected.get("origin", "unknown"))
    library_changed(directory)
    return path


def install_update(update, directory, progress, cancelled):
    from wordcel.utils.progress import content_length, download_progress
    progress("Downloading " + update.title)
    with tempfile.TemporaryDirectory(prefix="wordcel-update-") as folder:
        archive = Path(folder) / "dictionary.zip"
        request = Request(publisher_url(update.url), headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=30) as response, archive.open("wb") as output:
            size, received = content_length(response), 0
            while chunk := response.read(1024 * 1024):
                if cancelled.is_set():
                    raise InterruptedError("Update cancelled.")
                received += len(chunk)
                if received > 2 * 1024**3:
                    raise ValueError("Dictionary download exceeds 2 GB.")
                output.write(chunk)
                progress(download_progress(update.title, received, size))
        from .archive import DictionaryArchive
        with DictionaryArchive(archive) as bundle:
            index = json.loads(bundle.read("index.json"))
        if str(index.get("revision", "")) != update.available:
            raise ValueError("Publisher revision changed. Check for updates again.")
        return replace_dictionary(archive, directory, update.identity, progress, cancelled.is_set)


def update_batch(updates, directory, progress, cancelled):
    changed, errors = False, []
    for update in updates:
        if cancelled.is_set():
            break
        try:
            install_update(update, directory, progress, cancelled)
            changed = True
        except InterruptedError:
            break
        except Exception as error:
            errors.append(f"{update.title}: {error}")
    status = "Update cancelled. Completed updates were kept." if cancelled.is_set() else "Dictionaries updated."
    return "\n".join([status, *errors]), changed
