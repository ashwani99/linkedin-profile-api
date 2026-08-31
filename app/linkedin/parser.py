"""
Maps raw Voyager `identity/dash/profiles` JSON into our ProfileResponse
schema.

REWRITTEN after a live 410 Gone proved the original endpoint
(and its nested `positionView`/`educationView`/`*View.elements` response
shape) had been deprecated by LinkedIn. The current API returns a FLAT
`included` array containing every entity — the profile itself, each
position, each education entry, etc. — all at the same level, tagged
with `$type` (an entity type string) and `entityUrn` rather than being
pre-grouped into named sections.

CONFIRMED (via a recent, dated third-party writeup on LinkedIn's current
dash API, cross-checked against the live 410 that motivated this
rewrite):
  - The primary profile entity: find the item in `included` whose
    `entityUrn` contains "fsd_profile:" and that has a `firstName` key.
    `firstName`, `lastName`, `headline`, `summary` live directly on it.
  - Position entities: `$type` ends with "Position". Fields `title`,
    `companyName`, `dateRange` (with `start`/`end`, each `{month,year}`)
    are on the object directly. No `dateRange.end` means "current".

NOT CONFIRMED — best-effort inference, following the same `$type`-suffix
pattern as positions, since no source covered these sections directly.
MUST be corrected against a real captured response:
  - Education, skill, certification, and language entity `$type` values
    and their field names.
  - Where the profile image lives on the profile entity.

Every extraction below uses .get()/defensive matching and records a
warning rather than raising when something doesn't parse as expected —
same philosophy as before, more load-bearing now given the schema
uncertainty is larger this time.
"""

from datetime import datetime, timezone
import json

from app.models.responses import Certification, Education, Experience, ProfileResponse


def _find_first(included: list[dict], predicate) -> dict | None:
    for item in included:
        if predicate(item):
            return item
    return None


def _find_all(included: list[dict], type_suffix: str) -> list[dict]:
    return [item for item in included if item.get("$type", "").endswith(type_suffix)]


def _date_range_to_duration(date_range: dict | None) -> str | None:
    """Dash API shape: {"start": {"month": M, "year": Y}, "end": {...}}.
    Missing 'end' means the position/entry is current."""
    if not date_range:
        return None

    def _fmt(date: dict | None) -> str | None:
        if not date or "year" not in date:
            return None
        month = date.get("month")
        return f"{month:02d}/{date['year']}" if month else str(date["year"])

    start = _fmt(date_range.get("start"))
    end = _fmt(date_range.get("end")) or "Present"
    if not start:
        return None
    return f"{start} - {end}"


def _resolve_location(profile_obj: dict, included: list[dict]) -> str | None:
    """CONFIRMED via real data: locationName/geoLocationName are null on
    the profile object itself. The actual location is a reference —
    profile_obj['geoLocation']['geoUrn'] — that must be resolved against
    a separate Geo entity elsewhere in `included`, keyed by entityUrn."""
    geo_urn = (profile_obj.get("geoLocation") or {}).get("geoUrn")
    if not geo_urn:
        return None
    geo_entity = _find_first(included, lambda item: item.get("entityUrn") == geo_urn)
    if not geo_entity:
        return None
    return geo_entity.get("defaultLocalizedName")


def _extract_image_url(profile_obj: dict) -> str | None:
    """CONFIRMED via real data: rootUrl alone is just a prefix — the
    usable URL is rootUrl + one artifact's fileIdentifyingUrlPathSegment
    (which carries the actual signed expiry token). Picks the
    largest-width artifact available."""
    candidate = profile_obj.get("profilePicture")
    if not isinstance(candidate, dict):
        return None
    vector = (candidate.get("displayImageReference") or {}).get("vectorImage") or candidate.get(
        "com.linkedin.common.VectorImage"
    )
    if not vector or not vector.get("rootUrl"):
        return None
    artifacts = vector.get("artifacts") or []
    if not artifacts:
        return vector["rootUrl"]  # fallback: incomplete, but better than nothing
    best = max(artifacts, key=lambda a: a.get("width", 0))
    return vector["rootUrl"] + best.get("fileIdentifyingUrlPathSegment", "")


def parse_profile(raw: dict, profile_url: str) -> ProfileResponse:
    warnings: list[str] = []
    included: list[dict] = raw.get("included") or []

    profile_obj = _find_first(
        included,
        lambda item: bool(item.get("firstName")) and "fsd_profile:" in item.get("entityUrn", ""),
    )
    if profile_obj is None:
        warnings.append("Could not locate the primary profile entity in the response.")
        profile_obj = {}

    first_name = profile_obj.get("firstName")
    last_name = profile_obj.get("lastName")
    name = " ".join(p for p in [first_name, last_name] if p) or None
    if not name:
        warnings.append("Could not extract name.")

    image_url = _extract_image_url(profile_obj)
    if not image_url:
        warnings.append("Profile image not available or in an unexpected format.")

    # --- experience (CONFIRMED shape) ---
    experience: list[Experience] = []
    for item in _find_all(included, "Position"):
        experience.append(
            Experience(
                title=item.get("title"),
                company=item.get("companyName"),
                location=item.get("locationName"),
                duration=_date_range_to_duration(item.get("dateRange")),
                description=item.get("description"),
            )
        )
    if not experience:
        warnings.append("No experience entries found (or none visible on this profile).")

    # --- education (UNCONFIRMED $type/field names — best-effort guess) ---
    education: list[Education] = []
    for item in _find_all(included, "Education"):
        school_name = item.get("schoolName") or (item.get("school") or {}).get("schoolName")
        education.append(
            Education(
                school=school_name,
                degree=item.get("degreeName"),
                duration=_date_range_to_duration(item.get("dateRange")),
            )
        )

    # --- skills (UNCONFIRMED) ---
    skills: list[str] = []
    for item in _find_all(included, "Skill"):
        skill_name = item.get("name")
        if skill_name:
            skills.append(skill_name)

    # --- certifications (UNCONFIRMED) ---
    certifications: list[Certification] = []
    for item in _find_all(included, "Certification"):
        certifications.append(
            Certification(
                name=item.get("name"),
                issuer=item.get("authority"),
                date=_date_range_to_duration(item.get("dateRange")) or item.get("licenseNumber"),
            )
        )

    # --- languages (UNCONFIRMED) ---
    languages: list[str] = []
    for item in _find_all(included, "Language"):
        lang_name = item.get("name")
        if lang_name:
            languages.append(lang_name)

    return ProfileResponse(
        profile_url=profile_url,
        name=name,
        headline=profile_obj.get("headline"),
        location=_resolve_location(profile_obj, included),
        about=profile_obj.get("summary"),
        profile_image_url=image_url,
        experience=experience,
        education=education,
        skills=skills,
        certifications=certifications,
        languages=languages,
        scraped_at=datetime.now(timezone.utc),
        warnings=warnings,
    )