# Paper research data models

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Paper:
    """
    Represents a scholarly paper with metadata and local file path.
    """
    title: str
    doi: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    pmid: Optional[str] = None
    oa_status: bool = False          # True = open access
    pdf_url: Optional[str] = None    # URL to OA PDF (from Unpaywall)
    pdf_path: Optional[str] = None   # Local path after download
    citations: int = 0               # Citation count from CrossRef
    abstract: Optional[str] = None
    query_used: Optional[str] = None  # Original search query

    @property
    def authors_str(self) -> str:
        if not self.authors:
            return "Unknown"
        if len(self.authors) <= 3:
            return ", ".join(self.authors)
        return f"{self.authors[0]} et al."

    @property
    def filename(self) -> str:
        """Safe filename for PDF storage."""
        safe = self.title[:50].replace("/", "-").replace(":", "-").replace("?", "")
        year = self.year or "unknown"
        return f"{year}_{safe}.pdf"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "doi": self.doi,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "pmid": self.pmid,
            "oa_status": self.oa_status,
            "pdf_url": self.pdf_url,
            "pdf_path": self.pdf_path,
            "citations": self.citations,
            "abstract": self.abstract,
            "query_used": self.query_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Paper":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})