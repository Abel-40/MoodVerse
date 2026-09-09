"""Runtime AI provider: turns a reflection into structured emotional data.

The boundary this file exists to hold:

    The provider analyses what the USER wrote. It never produces scripture,
    never selects which scripture is returned, and never sees a request to.

Scripture comes from the database, always. If retrieval finds nothing suitable,
the correct answer is that nothing suitable was found - never a generated
passage. Nothing here has access to the corpus, which makes that structural
rather than a matter of prompt discipline.

Corpus enrichment does NOT use this. That work is done offline by the
development agent and committed; see docs/backend.md.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings, get_settings

# Mirrors the Phase 1 taxonomy. Kept as literals rather than imported from the
# pipeline so the backend has no runtime dependency on pipeline/ source.
EMOTIONS = frozenset({
    "anger", "anxiety", "awe", "confusion", "despair", "doubt", "exhaustion",
    "fear", "gratitude", "grief", "guilt", "hope", "joy", "loneliness", "peace",
    "sadness", "shame",
})
INTENTS = frozenset({
    "assurance", "comfort", "encouragement", "forgiveness", "gratitude",
    "guidance", "hope", "instruction", "lament", "patience", "peace",
    "perseverance", "praise", "repentance", "strength", "warning", "wisdom",
})
THEMES_MAX = 6


class ReflectionAnalysis(BaseModel):
    """Validated provider output. A response that fails this is rejected.

    Rejected and retried, never repaired - the same rule the enrichment
    pipeline follows. Silently correcting a malformed analysis is silently
    reinterpreting what the user said.
    """

    primary_emotion: str
    secondary_emotions: list[str] = Field(default_factory=list, max_length=4)
    intensity: int = Field(ge=1, le=4)
    intent: str
    themes: list[str] = Field(default_factory=list, max_length=THEMES_MAX)
    # Set when the reflection suggests acute risk. Narrows retrieval to
    # crisis-safe records; it does not trigger any automated intervention.
    crisis_signals: bool = False

    @field_validator("primary_emotion")
    @classmethod
    def _known_emotion(cls, value: str) -> str:
        if value not in EMOTIONS:
            raise ValueError(f"unknown emotion {value!r}")
        return value

    @field_validator("secondary_emotions")
    @classmethod
    def _known_secondaries(cls, values: list[str]) -> list[str]:
        unknown = [v for v in values if v not in EMOTIONS]
        if unknown:
            raise ValueError(f"unknown emotions {unknown!r}")
        return values

    @field_validator("intent")
    @classmethod
    def _known_intent(cls, value: str) -> str:
        if value not in INTENTS:
            raise ValueError(f"unknown intent {value!r}")
        return value


class AIProvider(ABC):
    """The interface the application depends on.

    Swapping provider means adding a subclass. It must never mean editing the
    retrieval engine, the schema, or the API surface.
    """

    name: str = "abstract"

    @abstractmethod
    def analyse(self, reflection_text: str) -> ReflectionAnalysis:
        """Analyse a reflection into validated structured data."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier recorded on the reflection row for auditability."""


class HeuristicProvider(AIProvider):
    """Deterministic keyword provider. No network, no key, no cost.

    Exists so the retrieval stack can be developed and tested end to end
    without a provider account, and so tests never depend on a live API. It is
    a lexical fallback, not a substitute for a real analysis provider.
    """

    name = "heuristic"

    _CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("grief", ("grief", "died", "death", "loss", "lost", "funeral", "mourn")),
        ("loneliness", ("lonely", "alone", "isolated", "no one", "nobody")),
        ("anxiety", ("anxious", "worried", "worry", "panic", "nervous", "afraid of")),
        ("fear", ("afraid", "scared", "terrified", "fear")),
        ("despair", ("hopeless", "pointless", "give up", "cannot go on", "despair")),
        ("exhaustion", ("exhausted", "tired", "drained", "burnt out", "burned out")),
        ("guilt", ("guilty", "my fault", "i failed", "ashamed of what i did")),
        ("shame", ("ashamed", "worthless", "disgusted with myself")),
        ("anger", ("angry", "furious", "rage", "resent", "bitter")),
        ("confusion", ("confused", "lost", "do not know what", "unsure", "torn")),
        ("doubt", ("doubt", "questioning", "not sure i believe")),
        ("sadness", ("sad", "down", "unhappy", "miserable")),
        ("gratitude", ("grateful", "thankful", "blessed")),
        ("joy", ("happy", "joyful", "delighted", "celebrating")),
        ("hope", ("hopeful", "looking forward")),
        ("peace", ("peaceful", "calm", "settled")),
    )

    _INTENT_BY_EMOTION: dict[str, str] = {
        "grief": "comfort",
        "loneliness": "comfort",
        "sadness": "comfort",
        "despair": "hope",
        "anxiety": "peace",
        "fear": "assurance",
        "exhaustion": "strength",
        "confusion": "guidance",
        "doubt": "assurance",
        "guilt": "forgiveness",
        "shame": "forgiveness",
        "anger": "patience",
        "gratitude": "gratitude",
        "joy": "praise",
        "hope": "encouragement",
        "peace": "peace",
        "awe": "praise",
    }

    _CRISIS_CUES = (
        "kill myself", "end my life", "suicide", "self harm", "self-harm",
        "not want to live", "better off dead",
    )

    @property
    def model_id(self) -> str:
        return "heuristic-v1"

    def analyse(self, reflection_text: str) -> ReflectionAnalysis:
        haystack = reflection_text.lower()

        matched: list[str] = []
        for emotion, cues in self._CUES:
            if any(cue in haystack for cue in cues):
                matched.append(emotion)

        primary = matched[0] if matched else "confusion"
        secondary = matched[1:4]

        # Intensity from explicit intensifiers and length, clamped to the scale.
        intensity = 2
        if any(w in haystack for w in ("very", "so ", "completely", "totally", "cannot")):
            intensity = 3
        if any(w in haystack for w in ("unbearable", "overwhelming", "desperate")):
            intensity = 4

        crisis = any(cue in haystack for cue in self._CRISIS_CUES)
        if crisis:
            intensity = 4

        return ReflectionAnalysis(
            primary_emotion=primary,
            secondary_emotions=secondary,
            intensity=intensity,
            intent=self._INTENT_BY_EMOTION.get(primary, "comfort"),
            themes=[],
            crisis_signals=crisis,
        )


class GeminiProvider(AIProvider):
    """Runtime reflection analysis on a free-tier key.

    The key is read from settings, held server-side, and never logged or
    returned. The prompt asks only for an analysis of the user's own words; no
    scripture is supplied to the model and none is requested from it.
    """

    name = "gemini"
    _API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

    _PROMPT = (
        "Analyse the emotional content of the reflection below.\n\n"
        "Return ONLY a JSON object with these keys:\n"
        "  primary_emotion       one of: {emotions}\n"
        "  secondary_emotions    up to 3, from the same list\n"
        "  intensity             integer 1-4\n"
        "  intent                one of: {intents}\n"
        "  themes                up to 6 short lowercase keywords\n"
        "  crisis_signals        true only if the text indicates risk of self-harm\n\n"
        "Rules you must follow:\n"
        "  - Describe only what the person wrote. Do not advise them.\n"
        "  - Do NOT quote, cite, paraphrase or produce any scripture, verse "
        "reference, book name or chapter number. Scripture is selected "
        "elsewhere and is not your task.\n"
        "  - If the text is ambiguous, choose the most defensible reading "
        "rather than inventing detail.\n\n"
        "Reflection:\n{reflection}\n"
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Set it in the environment or the "
                "backend .env, or configure AI_PROVIDER=heuristic."
            )

    @property
    def model_id(self) -> str:
        return self._settings.gemini_model

    def analyse(self, reflection_text: str) -> ReflectionAnalysis:
        prompt = self._PROMPT.format(
            emotions=", ".join(sorted(EMOTIONS)),
            intents=", ".join(sorted(INTENTS)),
            reflection=reflection_text,
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        request = urllib.request.Request(
            f"{self._API_ROOT}/{self._settings.gemini_model}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._settings.gemini_api_key or "",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"reflection analysis failed: {exc}") from exc

        text = body["candidates"][0]["content"]["parts"][0]["text"]
        # Rejected on failure, never repaired.
        return ReflectionAnalysis.model_validate_json(text)


def get_provider(settings: Settings | None = None) -> AIProvider:
    """Resolve the configured provider. The only place a provider is chosen."""
    settings = settings or get_settings()
    if settings.ai_provider == "gemini":
        return GeminiProvider(settings)
    if settings.ai_provider == "heuristic":
        return HeuristicProvider()
    raise ValueError(f"unknown AI_PROVIDER {settings.ai_provider!r}")
