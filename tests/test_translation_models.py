import unittest
from wordcel.translation_catalog import MODELS, fit_message, model_label, recommend_model
from wordcel.dictionary.translation import TranslationSettings


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
        self.assertIsNone(recommend_model(5 * gib))
        self.assertEqual(recommend_model(8 * gib), "lightweight")
        self.assertIsNone(recommend_model(8 * gib, 2 * gib, offload=True))
        self.assertIn("unknown", fit_message("compact", None))
        self.assertIn("insufficient", fit_message("quality", 8 * gib))
