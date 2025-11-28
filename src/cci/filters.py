"""
URL filtering for Claude-Code-Inspector.

Provides pattern-based filtering to capture only relevant LLM API traffic.
"""

import re
from re import Pattern

from cci.config import FilterConfig
from cci.logger import get_logger


class URLFilter:
    """
    URL filter based on include/exclude patterns.

    Include patterns are checked first, then exclude patterns.
    If no include patterns match, the URL is rejected.
    If any exclude pattern matches, the URL is rejected.
    """

    def __init__(self, config: FilterConfig):
        """
        Initialize the URL filter with the given configuration.

        Args:
            config: FilterConfig with include and exclude patterns
        """
        self.include_patterns: list[Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in config.include_patterns
        ]
        self.exclude_patterns: list[Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in config.exclude_patterns
        ]
        self._logger = get_logger()

    def should_capture(self, url: str) -> bool:
        """
        Determine if a URL should be captured.

        Args:
            url: The full URL to check

        Returns:
            True if the URL should be captured, False otherwise
        """
        # Check exclude patterns first (highest priority)
        for pattern in self.exclude_patterns:
            if pattern.search(url):
                self._logger.debug("URL excluded by pattern: %s", url)
                return False

        # Check include patterns
        for pattern in self.include_patterns:
            if pattern.search(url):
                self._logger.debug("URL matched include pattern: %s", url)
                return True

        # No match - don't capture
        return False

    def add_include_pattern(self, pattern: str) -> None:
        """Add an include pattern at runtime."""
        self.include_patterns.append(re.compile(pattern, re.IGNORECASE))

    def add_exclude_pattern(self, pattern: str) -> None:
        """Add an exclude pattern at runtime."""
        self.exclude_patterns.append(re.compile(pattern, re.IGNORECASE))


# Common LLM API endpoints for reference
KNOWN_LLM_ENDPOINTS = {
    "anthropic": [
        r".*api\.anthropic\.com/v1/messages.*",
        r".*api\.anthropic\.com/v1/complete.*",
    ],
    "openai": [
        r".*api\.openai\.com/v1/chat/completions.*",
        r".*api\.openai\.com/v1/completions.*",
        r".*api\.openai\.com/v1/embeddings.*",
    ],
    "google": [
        r".*generativelanguage\.googleapis\.com/v1.*",
        r".*generativelanguage\.googleapis\.com/v1beta.*",
    ],
    "together": [
        r".*api\.together\.xyz/v1/.*",
    ],
    "groq": [
        r".*api\.groq\.com/openai/v1/.*",
    ],
    "mistral": [
        r".*api\.mistral\.ai/v1/.*",
    ],
    "cohere": [
        r".*api\.cohere\.ai/v1/.*",
    ],
    "deepseek": [
        r".*api\.deepseek\.com/v1/.*",
    ],
}


def get_provider_patterns(providers: list[str]) -> list[str]:
    """
    Get URL patterns for specific providers.

    Args:
        providers: List of provider names (e.g., ["anthropic", "openai"])

    Returns:
        List of regex patterns for the specified providers
    """
    patterns: list[str] = []
    for provider in providers:
        provider_lower = provider.lower()
        if provider_lower in KNOWN_LLM_ENDPOINTS:
            patterns.extend(KNOWN_LLM_ENDPOINTS[provider_lower])
    return patterns

