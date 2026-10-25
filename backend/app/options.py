from dataclasses import dataclass, field

from . import config


@dataclass
class Rules:
    min_disclaimer_seconds: float = config.MIN_DISCLAIMER_SECONDS
    min_text_height_pct: float = config.MIN_TEXT_HEIGHT_PCT
    reading_words_per_sec: float = config.READING_WORDS_PER_SEC
    claim_window_before: float = config.CLAIM_WINDOW_BEFORE
    claim_window_after: float = config.CLAIM_WINDOW_AFTER


@dataclass
class Options:
    mode: str = "fast"
    language: str | None = None
    script: str | None = None
    check_bias: bool = True
    check_claims: bool = True
    recheck: bool = True
    rules: Rules = field(default_factory=Rules)

    @property
    def profile(self) -> dict:
        return config.MODES[self.mode]
