"""Bounded offline Arabic lookup comparison; model setup is a separate action."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter


def ocr_fixtures(fixtures, component):
    """Feed real OCR controlled Arabic text images without capturing the desktop."""
    import io
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QRect, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtWidgets import QApplication
    from wordcel.gui.typography import document_font
    from wordcel.language.arabic import spelling
    from wordcel.ocr.context import hit_paragraphs
    from wordcel.ocr.providers.screenai.provider import ScreenAiOcr
    application = QApplication.instance() or QApplication([])
    provider = ScreenAiOcr(component, language="ar")
    result = []
    for index, (sentence, surface, lemma, *reading) in enumerate(fixtures):
        image = QImage(1100, 110, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.setPen(QColor("black"))
        painter.setFont(document_font(("Noto Naskh Arabic", "Segoe UI", "Arial")[index % 3], 32, "ar"))
        painter.drawText(QRect(20, 10, 1060, 90), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, sentence)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        paragraphs = provider.scan(Image.open(io.BytesIO(bytes(buffer.data())))) or []
        words = [word for paragraph in paragraphs for word in paragraph.words if spelling(word.text) == spelling(surface)]
        hit = hit_paragraphs(paragraphs, (words[0].box.center_x, words[0].box.center_y), "ar") if words else None
        result.append((hit.text, hit.query, lemma, reading, hit.start) if hit else (sentence, "", lemma, reading, 0))
    return result


def peak_memory(pid):
    if sys.platform != "win32":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    *((name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"))]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).resolve().parents[3] / "tests/fixtures/arabic_msa.json")
    parser.add_argument("--test-root", type=Path, help="Isolated model/data directory")
    parser.add_argument("--mode", choices=("dictionary", "stanza", "morphology"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ocr-component", type=Path, help="Compare actual Screen AI output from controlled text images")
    args = parser.parse_args()
    if args.test_root:
        from wordcel.utils.paths import WordcelPaths
        root = args.test_root.resolve()
        WordcelPaths.data_dir = property(lambda self: str(root / "data"))
        WordcelPaths.cache_dir = property(lambda self: str(root / "cache"))
    if args.mode == "stanza":
        from wordcel.optional_runtimes import runtime_site
        for feature in ("arabic",):
            sys.path.insert(0, str(runtime_site(feature)))
    from wordcel.dictionary.search import SearchEngine
    from wordcel.language.arabic import spelling, lexical_vowels_agree
    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    prepared = ocr_fixtures(fixtures, args.ocr_component) if args.ocr_component else [
        (sentence, surface, lemma, reading, sentence.index(surface)) for sentence, surface, lemma, *reading in fixtures]
    engine = SearchEngine(args.library)
    if args.mode == "stanza":
        from wordcel.language.stanza_analyzer import StanzaAnalyzer
        engine._analyzer = ("ar", StanzaAnalyzer(language="ar"))
    rows, times, peak = [], [], 0
    try:
        for sentence, surface, lemma, reading, start in prepared:
            if not surface:
                rows.append(dict(surface="", lemma=lemma, found=False, first=False, readings=0, ms=0, ocr_miss=True))
                continue
            began = perf_counter()
            if args.mode == "stanza":
                from unittest.mock import patch
                with patch("wordcel.language.arabic_resources.available", return_value=False):
                    entries = engine.library.lookup(surface, "ar") or engine._lemma_lookup(surface, "ar", (sentence, start, start+len(surface)))
            else:
                result = engine.search(surface, source="ar", morphology=args.mode != "dictionary",
                                       context=(sentence, start, start+len(surface)))
                entries = result.entries
            elapsed = (perf_counter() - began) * 1000
            times.append(elapsed)
            expected = [e for e in entries if spelling(e.term) == spelling(lemma)
                        and (not reading or lexical_vowels_agree(reading[0], e.reading or e.term))]
            rows.append(dict(surface=surface, lemma=lemma, found=bool(expected),
                             first=bool(expected and entries[0] in expected), readings=len({(e.term, e.reading) for e in entries}), ms=round(elapsed, 2)))
            if args.mode == "morphology":
                from wordcel.language.arabic_analyzer import _worker
                if _worker is not None:
                    peak = max(peak, peak_memory(_worker.pid) or 0)
        warm = times[1:]
        report = dict(mode=args.mode, input="ocr" if args.ocr_component else "text", count=len(rows),
                              ocr_misses=sum(r.get("ocr_miss", False) for r in rows), found=sum(r["found"] for r in rows),
                              first=sum(r["first"] for r in rows), cold_ms=round(times[0], 2),
                              warm_median_ms=round(statistics.median(warm), 2), warm_max_ms=round(max(warm), 2),
                              peak_worker_mib=round(peak / 1024**2, 1) if peak else None, rows=rows)
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        engine.close()


if __name__ == "__main__":
    main()
