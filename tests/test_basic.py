"""Basic tests for LLM Interceptor."""

import pytest

from cci import __version__
from cci.config import CCIConfig, FilterConfig
from cci.filters import URLFilter
from cci.models import RecordType, RequestRecord
from cci.storage import JSONLWriter


class TestVersion:
    """Test version information."""

    def test_version_exists(self) -> None:
        """Test that version is defined."""
        assert __version__ is not None
        assert isinstance(__version__, str)

    def test_version_format(self) -> None:
        """Test that version follows semver format."""
        parts = __version__.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()


class TestConfig:
    """Test configuration module."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = CCIConfig()
        assert config.proxy.host == "127.0.0.1"
        assert config.proxy.port == 9090
        assert config.masking.mask_auth_headers is True

    def test_filter_config_defaults(self) -> None:
        """Test default filter patterns include major LLM providers."""
        config = FilterConfig()
        patterns = config.include_patterns
        assert any("anthropic" in p for p in patterns)
        assert any("openai" in p for p in patterns)
        assert any("googleapis" in p for p in patterns)


class TestURLFilter:
    """Test URL filtering."""

    def test_anthropic_url_matches(self) -> None:
        """Test that Anthropic API URLs are matched."""
        config = FilterConfig()
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://api.anthropic.com/v1/messages")

    def test_openai_url_matches(self) -> None:
        """Test that OpenAI API URLs are matched."""
        config = FilterConfig()
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://api.openai.com/v1/chat/completions")

    def test_random_url_not_matched(self) -> None:
        """Test that random URLs are not matched."""
        config = FilterConfig()
        url_filter = URLFilter(config)
        assert not url_filter.should_capture("https://example.com/api")

    def test_exclude_pattern(self) -> None:
        """Test that exclude patterns work."""
        config = FilterConfig(
            include_patterns=[".*example\\.com.*"],
            exclude_patterns=[".*health.*"],
        )
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://example.com/api")
        assert not url_filter.should_capture("https://example.com/health")


class TestURLFilterGlob:
    """Test URL filtering with glob patterns."""

    def test_glob_include_pattern(self) -> None:
        """Test that glob include patterns work."""
        config = FilterConfig(
            include_patterns=[],  # Clear default regex patterns
            include_globs=["*api.example.com*"],
        )
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://api.example.com/v1/messages")
        assert url_filter.should_capture("https://api.example.com/health")
        assert not url_filter.should_capture("https://other.com/api")

    def test_glob_exclude_pattern(self) -> None:
        """Test that glob exclude patterns work."""
        config = FilterConfig(
            include_patterns=[],
            include_globs=["*example.com*"],
            exclude_globs=["*health*"],
        )
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://example.com/api")
        assert not url_filter.should_capture("https://example.com/health")

    def test_glob_wildcard_subdomain(self) -> None:
        """Test that glob patterns match subdomains."""
        config = FilterConfig(
            include_patterns=[],
            include_globs=["*.my-custom-api.com*"],
        )
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://api.my-custom-api.com/v1/chat")
        assert url_filter.should_capture("https://test.my-custom-api.com/api")
        assert not url_filter.should_capture("https://my-custom-api.org/api")

    def test_glob_case_insensitive(self) -> None:
        """Test that glob matching is case insensitive."""
        config = FilterConfig(
            include_patterns=[],
            include_globs=["*api.example.com*"],
        )
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://API.EXAMPLE.COM/v1/messages")
        assert url_filter.should_capture("https://Api.Example.Com/v1/messages")

    def test_glob_add_at_runtime(self) -> None:
        """Test adding glob patterns at runtime."""
        config = FilterConfig(include_patterns=[])
        url_filter = URLFilter(config)

        # Initially no match
        assert not url_filter.should_capture("https://api.newsite.com/v1")

        # Add glob pattern at runtime
        url_filter.add_include_glob("*newsite.com*")
        assert url_filter.should_capture("https://api.newsite.com/v1")

    def test_glob_question_mark_wildcard(self) -> None:
        """Test that ? matches single character."""
        config = FilterConfig(
            include_patterns=[],
            include_globs=["*api?.example.com*"],
        )
        url_filter = URLFilter(config)
        assert url_filter.should_capture("https://api1.example.com/v1")
        assert url_filter.should_capture("https://apix.example.com/v1")
        assert not url_filter.should_capture("https://api.example.com/v1")
        assert not url_filter.should_capture("https://api12.example.com/v1")

    def test_glob_with_regex_patterns(self) -> None:
        """Test that glob and regex patterns work together."""
        config = FilterConfig(
            include_patterns=[".*anthropic\\.com.*"],  # Regex pattern
            include_globs=["*openai.com*"],  # Glob pattern
        )
        url_filter = URLFilter(config)
        # Regex pattern should match
        assert url_filter.should_capture("https://api.anthropic.com/v1/messages")
        # Glob pattern should match
        assert url_filter.should_capture("https://api.openai.com/v1/chat")
        # Neither should match
        assert not url_filter.should_capture("https://example.com/api")


class TestModels:
    """Test data models."""

    def test_request_record_creation(self) -> None:
        """Test creating a request record."""
        record = RequestRecord(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
        )
        assert record.type == RecordType.REQUEST
        assert record.method == "POST"
        assert record.id is not None

    def test_request_record_with_body(self) -> None:
        """Test request record with body."""
        body = {"model": "claude-3-sonnet", "messages": []}
        record = RequestRecord(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
            body=body,
        )
        assert record.body == body


class TestStorage:
    """Test storage module."""

    def test_jsonl_writer_creation(self, tmp_path: pytest.TempPathFactory) -> None:
        """Test creating a JSONL writer."""
        output_file = tmp_path / "test.jsonl"  # type: ignore
        writer = JSONLWriter(output_file)
        assert writer.output_path == output_file

    def test_jsonl_writer_write(self, tmp_path: pytest.TempPathFactory) -> None:
        """Test writing records to JSONL."""
        output_file = tmp_path / "test.jsonl"  # type: ignore
        with JSONLWriter(output_file) as writer:
            record = RequestRecord(
                method="POST",
                url="https://api.anthropic.com/v1/messages",
            )
            writer.write_record(record)

        # Read and verify
        with open(output_file) as f:
            content = f.read()
        assert "request" in content
        assert "anthropic" in content
