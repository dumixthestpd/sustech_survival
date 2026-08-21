# =============================================================================
# PubMed / NCBI — Direct API Authorizer
# =============================================================================
# PubMed/NCBI uses Entrez API. No login needed for basic search.
# An API key (from your NCBI account) gives higher rate limits:
#   - Without key: 3 requests/second
#   - With key: 10 requests/second
#
# To get a key: https://www.ncbi.nlm.nih.gov/account/ → API Keys
# =============================================================================

import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

from ..authorizer import Authorizer

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov"
ENTREZ_EUTILS = f"{NCBI_BASE}/entrez/eutils"


class PubMedAuth(Authorizer):
    """
    Headless PubMed search via NCBI Entrez API.

    Usage:
        pubmed = PubMedAuth()
        pubmed.search("electrochromic polymer", max_results=10)
        pubmed.fetch_pmids([...])
    """

    BASE_URL = NCBI_BASE
    API_KEY: Optional[str] = None  # Set from credentials or None for anonymous

    def __init__(self, api_key: Optional[str] = None, skill_dir: Optional[str] = None):
        self.api_key = api_key or self.API_KEY
        super().__init__(skill_dir=skill_dir)
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "sustech_survival/1.0 (+https://github.com/dumixthestpd/sustech_survival/issues)",
            "Accept": "application/json",
        })

    # ── Public API ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 20,
        datetype: str = "pdat",
        mindate: Optional[str] = None,
        maxdate: Optional[str] = None,
    ) -> dict:
        """
        Search PubMed and return matched PMIDs with basic metadata.

        Args:
            query: PubMed search query (use [TI], [AB], [AU] etc.)
            max_results: How many PMIDs to return (max 100k, but we default to 20)
            datetype: "pdat" (publication date) or "edat" (Entrez date)
            mindate/maxdate: YYYY or YYYY/MM or YYYY/MM/DD
        Returns:
            {"pmids": [...], "count": N, "query": "...", "next_cursor": ...}
        """
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": min(max_results, 100_000),
            "retmode": "json",
            "usehistory": "n",
            "sort": "relevance",
        }
        if mindate:
            params["mindate"] = mindate
        if maxdate:
            params["maxdate"] = maxdate
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{ENTREZ_EUTILS}/esearch.fcgi?{urlencode(params)}"
        r = self.http.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        esearch = data.get("esearchresult", {})
        pmids = esearch.get("idlist", [])
        count = int(esearch.get("count", 0))
        cursor = esearch.get("idlist", [None] * len(pmids))

        return {
            "pmids": pmids,
            "count": count,
            "query": query,
            "next_cursor": cursor[-1] if len(cursor) == max_results else None,
        }

    def fetch_abstracts(self, pmids: list[str]) -> list[dict]:
        """
        Fetch abstracts and metadata for a list of PMIDs (batch of up to 200).
        Returns list of {"pmid", "title", "abstract", "authors", "journal", "year"}.
        """
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(str(p) for p in pmids[:200]),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{ENTREZ_EUTILS}/efetch.fcgi?{urlencode(params)}"
        r = self.http.get(url, timeout=30)
        r.raise_for_status()

        return self.parse_abstracts_xml(r.text)

    def fetch_citations(self, pmid: str) -> dict:
        """Fetch a single PMID's full citation record."""
        return self.fetch_abstracts([pmid])[0]

    def cited_by(self, pmid: str, max_results: int = 20) -> list[str]:
        """Get PMIDs that cite the given PMID."""
        return self.search(f"{pmid}[pmid]", max_results=max_results)["pmids"]

    # ── Internals ────────────────────────────────────────────────────────────

    def parse_abstracts_xml(self, xml_text: str) -> list[dict]:
        results = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return results

        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//PMID")
            if pmid_el is None:
                continue
            pmid = pmid_el.text or ""

            title_el = article.find(".//ArticleTitle")
            title = "".join(title_el.text or "" for title_el in [title_el] if title_el is not None)
            if not title:
                title = article.findtext(".//BookTitle", "")

            abstract_els = article.findall(".//AbstractText")
            abstract = " ".join(el.text or "" for el in abstract_els)

            authors = []
            for author in article.findall(".//Author"):
                last = author.findtext("LastName", "")
                fore = author.findtext("ForeName", "")
                if last:
                    authors.append(f"{fore} {last}".strip())

            journal_el = article.find(".//Journal/Title")
            journal = journal_el.text if journal_el is not None else ""
            year_el = article.find(".//PubDate/Year")
            year = year_el.text if year_el is not None else ""

            results.append({
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal": journal,
                "year": year,
            })

        return results

    # ── Authenticator interface ────────────────────────────────────────────────

    def check(self) -> tuple[bool, str]:
        """Always OK — PubMed Entrez is free."""
        return True, "NCBI Entrez API — no auth required"

    def login(self, username: str, password: str) -> bool:
        """NCBI uses API keys, not passwords. Set API_KEY instead."""
        if len(username) > 10 and not password:
            # Assume username is actually an API key
            self.api_key = username
            return True
        return False


_pubmed = PubMedAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
