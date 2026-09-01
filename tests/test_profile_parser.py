import json
from pathlib import Path

import pytest

from app.linkedin.parser import parse_profile

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def full_response():
    return _load_fixture("sample_voyager_response.json")


@pytest.fixture
def minimal_response():
    return _load_fixture("sample_voyager_response_minimal.json")


class TestFullProfile:
    def test_name_and_headline(self, full_response):
        result = parse_profile(full_response, profile_url="https://linkedin.com/in/jane-doe-12345")
        assert result.name == "Jane Doe"
        assert result.headline == "Senior Software Engineer at Acme Corp"
        assert result.location == "San Francisco Bay Area"
        assert result.about is not None

    def test_experience_company_names(self, full_response):
        result = parse_profile(full_response, profile_url="https://linkedin.com/in/jane-doe-12345")
        assert len(result.experience) == 2
        assert result.experience[0].company == "Acme Corp"
        assert result.experience[1].company == "Beta Inc"

    def test_experience_duration_formatting(self, full_response):
        result = parse_profile(full_response, profile_url="https://linkedin.com/in/jane-doe-12345")
        assert result.experience[1].duration == "2018 - 2021"
        assert result.experience[0].duration == "2021 - Present"

    def test_education_skills_certifications_languages(self, full_response):
        result = parse_profile(full_response, profile_url="https://linkedin.com/in/jane-doe-12345")
        assert len(result.education) == 1
        assert result.education[0].school == "State University"
        assert "Python" in result.skills
        assert len(result.certifications) == 1
        assert result.certifications[0].issuer == "Amazon Web Services"
        assert set(result.languages) == {"English", "Spanish"}

    def test_profile_image_url_extracted(self, full_response):
        result = parse_profile(full_response, profile_url="https://linkedin.com/in/jane-doe-12345")
        assert result.profile_image_url is not None
        assert result.profile_image_url.startswith("https://")

    def test_no_warnings_on_complete_profile(self, full_response):
        result = parse_profile(full_response, profile_url="https://linkedin.com/in/jane-doe-12345")
        assert result.warnings == []


class TestMinimalProfile:
    """Defensive-path tests: every optional section is absent. Parser
    must degrade gracefully — never raise, return sensible fallbacks,
    and record warnings for what couldn't be extracted."""

    def test_does_not_raise(self, minimal_response):
        result = parse_profile(minimal_response, profile_url="https://linkedin.com/in/john-smith-99")
        assert result.name == "John Smith"

    def test_missing_sections_default_to_empty(self, minimal_response):
        result = parse_profile(minimal_response, profile_url="https://linkedin.com/in/john-smith-99")
        assert result.experience == []
        assert result.education == []
        assert result.skills == []
        assert result.certifications == []
        assert result.languages == []
        assert result.headline is None
        assert result.about is None

    def test_warnings_populated_for_missing_data(self, minimal_response):
        result = parse_profile(minimal_response, profile_url="https://linkedin.com/in/john-smith-99")
        assert any("experience" in w.lower() for w in result.warnings)
        assert any("image" in w.lower() for w in result.warnings)


def test_completely_empty_dict_does_not_raise():
    """Extreme edge case: raw is an empty dict entirely (e.g. Voyager
    returned `{}` for some reason). Should still produce a valid
    ProfileResponse, not crash."""
    result = parse_profile({}, profile_url="https://linkedin.com/in/nobody")
    assert result.name is None
    assert result.experience == []
    assert "Could not extract name." in result.warnings