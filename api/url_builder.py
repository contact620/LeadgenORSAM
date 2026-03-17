"""Build an Apollo.io search URL from structured filters."""

from urllib.parse import quote

from api.models import ApolloFilters

# Mapping: ApolloFilters field name -> Apollo query parameter name
_PARAM_MAP: dict[str, str] = {
    "person_titles": "personTitles[]",
    "locations": "organizationLocations[]",
    "industries": "industryTag[]",
    "employee_ranges": "organizationNumEmployeesRanges[]",
    "seniority": "personSeniorities[]",
    "email_status": "contactEmailStatus[]",
}


def build_apollo_url(filters: ApolloFilters) -> str:
    """Convert an ApolloFilters object into an Apollo.io search URL.

    Apollo uses a hash-based SPA URL: https://app.apollo.io/#/people?key=val&...
    Array parameters are repeated: personTitles[]=CEO&personTitles[]=CTO
    """
    parts: list[str] = []

    for field_name, param_name in _PARAM_MAP.items():
        values = getattr(filters, field_name, [])
        for v in values:
            parts.append(f"{param_name}={quote(v, safe=',')}")

    # Keywords use a single comma-joined parameter
    if filters.keywords:
        joined = ",".join(filters.keywords)
        parts.append(f"q_keywords={quote(joined)}")

    query_string = "&".join(parts)
    return f"https://app.apollo.io/#/people?{query_string}"
