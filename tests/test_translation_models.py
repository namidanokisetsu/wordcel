import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from wordcel.translation_catalog import MODELS, fit_message, model_label, recommend_model
from wordcel.dictionary.translation import TranslationSettings
from wordcel.translation_models import (
    list_hub_models, local_model, model_catalog, model_identity, validate_custom_spec,
)


class ModelCatalogTests(unittest.TestCase):
    def test_saved_model_names_keep_their_existing_quantization(self):
        for identity in ("quality", "lightweight"):
            options = TranslationSettings(profile=identity, backend="cpu").validated()
            self.assertEqual(options.profile, identity)
            self.assertEqual(MODELS[identity]["quantization"], "Q8_0")
        self.assertEqual(TranslationSettings(profile="compact").validated().profile, "compact")
        self.assertEqual(MODELS["compact"]["size"], 1133080448)
        self.assertIn("1.1 GB", model_label("compact"))

    def test_recommendation_accounts_for_context_and_system_memory(self):
        gib = 1024**3
        self.assertIsNone(recommend_model(None))
        self.assertIsNone(recommend_model(4 * gib))
        self.assertEqual(recommend_model(8 * gib), "compact")
        self.assertIsNone(recommend_model(8 * gib, 2 * gib, offload=True))
        self.assertIn("unknown", fit_message("compact", None))
        self.assertIn("insufficient", fit_message("quality", 8 * gib))

    def test_custom_identity_and_settings_are_filesystem_independent(self):
        digest = hashlib.sha256(b"fixture").hexdigest()
        identity = model_identity({"sha256": digest})
        options = TranslationSettings(profile=identity).validated()
        self.assertEqual(options.profile, identity)
        with self.assertRaises(ValueError):
            TranslationSettings(profile="gguf:" + "A" * 64).validated()

    def test_local_model_descriptor_is_stable_and_catalogued(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture-F16.gguf"
            path.write_bytes(b"GGUFfixture")
            spec = local_model(path)
        self.assertEqual(spec["quantization"], "F16")
        self.assertEqual(spec["profile"], model_identity(spec))
        self.assertEqual(model_catalog(registry={"custom_models": {spec["profile"]: spec}})[spec["profile"]], spec)

    def test_hub_descriptor_uses_commit_and_publisher_digest(self):
        digest = hashlib.sha256(b"hub").hexdigest()
        fake = types.SimpleNamespace(HfApi=lambda: types.SimpleNamespace(model_info=lambda repo_id, files_metadata, token: types.SimpleNamespace(
            sha="a" * 40, siblings=[types.SimpleNamespace(rfilename="model-F16.gguf", size=3,
                                                              lfs=types.SimpleNamespace(sha256=digest))])))
        with patch.dict(sys.modules, {"huggingface_hub": fake}):
            choices = list_hub_models("owner/model")
        self.assertEqual(choices[0]["repo_id"], "owner/model")
        self.assertEqual(choices[0]["revision"], "a" * 40)
        self.assertEqual(choices[0]["sha256"], digest)

    def test_bundle_metadata_requires_custom_payload_identity(self):
        from wordcel.resource_bundle import _sanitize_translation_manifest
        digest = hashlib.sha256(b"fixture").hexdigest()
        profile = "gguf:" + digest
        spec = validate_custom_spec(profile, {
            "source": "local", "source_file": "fixture.gguf", "size": 7,
            "sha256": digest, "name": "Fixture", "quantization": "F16",
        })
        manifest = {"custom_models": {profile: spec}, "models": {
            profile: {"path": spec["path"], "size": 7, "sha256": digest}}}
        self.assertEqual(_sanitize_translation_manifest(manifest)["custom_models"][profile]["file"], spec["file"])
        manifest["models"][profile]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            _sanitize_translation_manifest(manifest)
