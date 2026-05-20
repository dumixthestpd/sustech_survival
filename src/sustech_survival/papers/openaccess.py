# Unpaywall — open-access PDF resolution

import requests
from typing import Optional

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
EMAIL = "dumix@sustech.edu.cn"  # Required by Unpaywall TOS


def resolve_oa_pdf(doi: str) -> tuple[bool, Optional[str]]:
    """
    Query Unpaywall for open-access PDF URL of a DOI.

    Returns (is_oa, pdf_url). pdf_url is None if not open access.
    """
    if not doi or doi.startswith("10.12688") or ".suppl" in doi.lower() or ".s001" in doi.lower():
        return False, None

    try:
        r = requests.get(
            f"{UNPAYWALL_BASE}/{doi}",
            params={"email": EMAIL},
            timeout=10
        )
        if r.status_code == 404:
            return False, None
        if r.status_code != 200:
            return False, None

        data = r.json()
        is_oa = data.get("is_oa", False)
        if not is_oa:
            return False, None

        # Best OA location = most reliable open-access copy
        best = data.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf") or best.get("url") or None

        return True, pdf_url

    except Exception:
        return False, None


def resolve_many(dois: list[str]) -> dict[str, tuple[bool, Optional[str]]]:
    """
    Batch resolve OA status for multiple DOIs.
    Returns {doi: (is_oa, pdf_url)}.
    """
    results = {}
    for doi in dois:
        results[doi] = resolve_oa_pdf(doi)
    return results