"""Pinned managed models, independent of runtime hardware."""
MODELS = {
    "quality": dict(name="Hy-MT2-7B Q8_0", label="Quality", quantization="Q8_0", memory=12 * 1024**3, repo="Hy-MT2-7B-GGUF", revision="ab8472660ac61fac25f1af43fac2599d52a8a775",
                    file="HY-MT2-7B-Q8_0.gguf", size=7981928896,
                    sha256="58b3ad55dd6f6fa08c695cddc34fb5f8f708a844f78ae10508071914b0ed67c0"),
    "lightweight": dict(name="Hy-MT2-1.8B Q8_0", label="Lightweight", quantization="Q8_0", memory=4 * 1024**3, repo="Hy-MT2-1.8B-GGUF", revision="a0c709d9fac510f2c807aa3af52872340dc37a4a",
                        file="Hy-MT2-1.8B-Q8_0.gguf", size=1908528192,
                        sha256="5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4"),
    "compact": dict(name="Hy-MT2-1.8B Q4_K_M", label="Compact", quantization="Q4_K_M", memory=3 * 1024**3,
                    repo="Hy-MT2-1.8B-GGUF", revision="a0c709d9fac510f2c807aa3af52872340dc37a4a",
                    file="Hy-MT2-1.8B-Q4_K_M.gguf", size=1133080448,
                    sha256="dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699"),
}


def model_label(identity):
    model = MODELS[identity]
    return f'{model["label"]} ({model["size"] / 1e9:.2g} GB)'


def recommend_model(available_memory, gpu_memory=None, offload=False):
    """Reserve 2 GiB for the OS; budgets include weights, 8K context and buffers.

    Q8 remains the tested recommendation. Unknown/insufficient memory recommends
    no download. GPU memory contributes only with verified full offload.
    """
    if available_memory is None:
        return None
    budget = max(0, available_memory - 2 * 1024**3)
    if offload and gpu_memory is not None:
        budget = min(budget, gpu_memory)
    return "lightweight" if budget >= MODELS["lightweight"]["memory"] else None


def fit_message(identity, available_memory, gpu_memory=None, offload=False):
    model = MODELS[identity]
    if available_memory is None:
        return "Available memory unknown; choose a model explicitly"
    budget = max(0, available_memory - 2 * 1024**3)
    if offload and gpu_memory is not None:
        budget = min(budget, gpu_memory)
    return ("Estimated memory fits" if budget >= model["memory"] else "Available memory may be insufficient") + \
        f'; about {model["memory"] / 1024**3:g} GiB plus 2 GiB for the system'
