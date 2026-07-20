"""UTM landing-link builder (rule 3: campaign code travels with every post).

The «پست → کلیک → لندینگ» chain starts here: the landing URL compiled onto a
publish job carries utm_source/medium/campaign so M9 analytics can attribute
every click back to the exact post and campaign.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_id")


def build_landing_url(base_url: str, utm: dict) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("landing_url must be an http(s) URL")
    # Replace (never duplicate) utm_* params so re-compilation is idempotent.
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _UTM_KEYS
    ]
    pairs += [(key, str(utm[key])) for key in _UTM_KEYS if key in utm]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))
