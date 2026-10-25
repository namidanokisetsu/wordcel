import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


spec = importlib.util.spec_from_file_location("runtime_packaging", Path(__file__).resolve().parents[1] / "packaging/optional_runtimes.py")
runtime_packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_packaging)


class OptionalPackagingTests(unittest.TestCase):
    def test_removed_libraries_also_remove_aliases_and_link_chains(self):
        optional = str(Path("fixture/torch/lib/libtorch.dylib").resolve())
        core = str(Path("fixture/numpy/lib/libnumpy.dylib").resolve())
        analysis = SimpleNamespace(pure=[], binaries=[
            ("torch/lib/libtorch.dylib", optional, "BINARY"),
            ("libtorch.dylib", "torch/lib/libtorch.dylib", "SYMLINK"),
            ("numpy/lib/libnumpy.dylib", core, "BINARY"),
            ("libnumpy.dylib", "numpy/lib/libnumpy.dylib", "SYMLINK"),
        ], datas=[
            ("aliases/torch.dylib", "../libtorch.dylib", "SYMLINK"),
            ("torch-alias", "torch", "SYMLINK"),
            ("numpy-alias", "numpy", "SYMLINK"),
        ])
        runtime_packaging.strip(analysis, {os.path.normcase(optional)})
        self.assertEqual([entry[0] for entry in analysis.binaries], ["numpy/lib/libnumpy.dylib", "libnumpy.dylib"])
        self.assertEqual([entry[0] for entry in analysis.datas], ["numpy-alias"])

    def test_framework_directory_links_and_shared_resources_survive(self):
        analysis = SimpleNamespace(pure=[], binaries=[
            ("QtCore.framework/Versions/A/QtCore", "/core/QtCore", "BINARY"),
            ("QtCore.framework/Versions/Current", "A", "SYMLINK"),
            ("QtCore.framework/QtCore", "Versions/Current/QtCore", "SYMLINK"),
        ], datas=[
            ("QtCore.framework/Resources", "Versions/Current/Resources", "SYMLINK"),
            ("QtCore.framework/Versions/A/Resources/Info.plist", "/core/Info.plist", "DATA"),
        ])
        runtime_packaging.strip(analysis, set())
        self.assertEqual(len(analysis.binaries), 3)
        self.assertEqual(len(analysis.datas), 2)
