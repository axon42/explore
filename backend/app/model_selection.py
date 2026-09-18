"""Local provider selection; secrets never leave backend settings."""

from .analysis import GeminiAnalyzer, MockAnalyzer
from .models import DomainError
from .openai_analysis import OpenAIAnalyzer

CATALOG = {
    "gemini": ["gemini-3.1-flash-lite", "gemini-3.8-flash"],
    "openai": ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"],
    "mock": ["simulated"],
}


class ModelSelection:
    def __init__(self, storage, settings):
        self.storage, self.settings = storage, settings
        self.initial = {
            "provider": settings.analysis_provider,
            "model": "simulated"
            if settings.analysis_provider == "mock"
            else settings.openai_model
            if settings.analysis_provider == "openai"
            else settings.gemini_model,
            "revision": 0,
        }
        self.catalog = {k: list(v) for k, v in CATALOG.items()}
        for provider, model in [
            ("gemini", settings.gemini_model),
            ("openai", settings.openai_model),
        ]:
            if model not in self.catalog[provider]:
                self.catalog[provider].append(model)

    def configured(self, provider):
        return provider == "mock" or bool(self.key(provider))

    def key(self, provider):
        key = self.settings.openai_api_key if provider == "openai" else self.settings.gemini_api_key
        return key.get_secret_value()

    def get(self):
        with self.storage.connection() as db:
            row = db.execute(
                "SELECT provider,model,revision FROM model_selection WHERE id=1"
            ).fetchone()
            return dict(row) if row else dict(self.initial)

    def view(self):
        return {
            **self.get(),
            "options": [
                {"provider": provider, "model": model, "configured": self.configured(provider)}
                for provider, models in self.catalog.items()
                for model in models
            ],
        }

    def update(self, provider, model, revision):
        if provider not in self.catalog or model not in self.catalog[provider]:
            raise DomainError("invalid_model", "Choose a supported provider and model.", 422)
        if not self.configured(provider):
            raise DomainError(
                "analysis_unconfigured",
                f"Add {provider.upper()}_API_KEY on the server and restart.",
                422,
            )
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM model_selection WHERE id=1").fetchone()
            current = row[0] if row else 0
            if current != revision:
                raise DomainError(
                    "conflict", "Model selection changed in another tab. Refresh and retry."
                )
            db.execute(
                "INSERT INTO model_selection VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "provider=excluded.provider,model=excluded.model,revision=excluded.revision",
                (provider, model, current + 1),
            )
        return self.view()

    def analyzer(self, choice):
        provider, model = choice["provider"], choice["model"]
        if provider == "mock":
            return MockAnalyzer()
        cls = OpenAIAnalyzer if provider == "openai" else GeminiAnalyzer
        return cls(self.key(provider), model, timeout=self.settings.analysis_timeout_seconds - 1)
