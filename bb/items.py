# Items — BB item type hierarchy
"""
Item classes for all Blackboard content item types.
Each item represents a sub-element within a BB content page.
"""

import re
from typing import List, Tuple

try:
    from .session import BB_BASE
except ImportError:
    from session import BB_BASE


class Item:
    """
    Base class for all BB item types.

    All items share:
      sub_id, title, type (item type string), bb_url,
      description, description_html

    Subclasses:
      FileItem      — downloadable files (PDF, doc, etc.)
      VideoItem     — embedded video player (iframe)
      HomeworkItem  — assignment with uploadAssignment link
      InlineItem    — inline images embedded in page
      LinkItem      — external URL references
      TextItem      — description text only
      UnknownItem   — could not determine type
    """

    TYPE = "unknown"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = ""):
        self.sub_id = sub_id
        self.title = title
        self.bb_url = bb_url
        self.description = description
        self.description_html = description_html

    @property
    def item_type(self) -> str:
        """Item type identifier: file, video, homework, inline, link, text, unknown."""
        return self.TYPE

    @property
    def is_homework(self) -> bool:
        return self.TYPE == "homework"

    def _fmt_desc(self, max_len=38) -> str:
        p = self.description[:max_len].replace("\t", " ").strip()
        return p + ".." if len(self.description) > max_len else p

    def to_row(self) -> str:
        """Override in subclass for type-specific row format."""
        raise NotImplementedError

    def to_markdown(self) -> str:
        """Render this item as a Markdown string. Override in subclass."""
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return self.to_row()


# ── Item subclasses ───────────────────────────────────────────────────────────

class FileItem(Item):
    """Item with downloadable file attachments (PDF, doc, etc.)."""
    TYPE = "file"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = "",
                 files: list = None):
        super().__init__(sub_id, title, bb_url, description, description_html)
        self.files = files or []

    @property
    def has_attachment(self) -> bool:
        return bool(self.files)

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"{len(self.files)}\t0\t-\t-\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        if self.files:
            lines.append("**Attachments:**")
            for name, url in self.files:
                full = url if url.startswith("http") else BB_BASE + url
                lines.append(f"- [{name}]({full})")
        return "\n".join(lines)


class VideoItem(Item):
    """Item with an embedded video player (iframe)."""
    TYPE = "video"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = "",
                 video_url: str = ""):
        super().__init__(sub_id, title, bb_url, description, description_html)
        self.video_url = video_url

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t0\t-\t-\t{desc}\n"
                f"           video_url: {self.video_url}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        if self.video_url:
            lines.append(f"**Video:** {self.video_url}\n")
        return "\n".join(lines)


class HomeworkItem(Item):
    """Item with a homework/uploadAssignment link. May also have template files."""
    TYPE = "homework"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = "",
                 files: list = None, submission_count: int = 0, deadline: str = ""):
        super().__init__(sub_id, title, bb_url, description, description_html)
        self.files = files or []
        self.submission_count = submission_count
        self.deadline = deadline

    @property
    def has_attachment(self) -> bool:
        return bool(self.files)

    def to_row(self) -> str:
        deadline_str = self.deadline or "-"
        sub_count = str(self.submission_count)
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"{len(self.files)}\t0\t{sub_count}\t{deadline_str}\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        if self.files:
            lines.append("**Attachments:**")
            for name, url in self.files:
                full = url if url.startswith("http") else BB_BASE + url
                lines.append(f"- [{name}]({full})")
        deadline_note = (f"\n> **Deadline** (system-recorded): {self.deadline}"
                         if self.deadline else "")
        if self.submission_count > 0:
            lines.append(
                f"\n**[Homework Submission]** — "
                f"{self.submission_count} submission(s) made.{deadline_note}"
            )
        else:
            lines.append(
                f"\n**[Homework Submission]** — not submitted yet."
                f"{deadline_note}"
            )
        return "\n".join(lines)


class InlineItem(Item):
    """Item with inline images embedded in the page content (not downloadable)."""
    TYPE = "inline"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = "",
                 inline_imgs: list = None):
        super().__init__(sub_id, title, bb_url, description, description_html)
        self.inline_imgs = inline_imgs or []

    @property
    def has_inline_content(self) -> bool:
        return bool(self.inline_imgs)

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t{len(self.inline_imgs)}\t-\t-\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        for url in self.inline_imgs:
            lines.append(f"![inline image]({url})")
        return "\n".join(lines)


class LinkItem(Item):
    """Item with external URL references only."""
    TYPE = "link"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = "",
                 ext_urls: list = None):
        super().__init__(sub_id, title, bb_url, description, description_html)
        self.ext_urls = ext_urls or []

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t0\t-\t-\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        for text, url in self.ext_urls:
            if text:
                lines.append(f"[{text}]({url})")
            else:
                lines.append(f"<{url}>")
        return "\n".join(lines)


class TextItem(Item):
    """Item with description text only, no files or links."""
    TYPE = "text"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = ""):
        super().__init__(sub_id, title, bb_url, description, description_html)

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t0\t-\t-\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        return "\n".join(lines)


class FolderItem(Item):
    """Item that links to another BB content page (a folder in the BB tree)."""
    TYPE = "folder"

    def __init__(self, sub_id: str, title: str, bb_url: str = "",
                 description: str = "", description_html: str = ""):
        super().__init__(sub_id, title, bb_url, description, description_html)

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t0\t-\t-\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.description:
            lines.append(f"{self.description}\n")
        if self.bb_url:
            lines.append(f"**→ [Open folder]({self.bb_url})**\n")
        return "\n".join(lines)


class UnknownItem(Item):
    """Item that could not be classified into any known type."""
    TYPE = "unknown"

    def to_row(self) -> str:
        desc = self._fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t0\t-\t-\t{desc}")


# Registry for subclass dispatch by type string
_ITEM_REGISTRY = {
    "file": FileItem,
    "video": VideoItem,
    "homework": HomeworkItem,
    "folder": FolderItem,
    "inline": InlineItem,
    "link": LinkItem,
    "text": TextItem,
    "unknown": UnknownItem,
}


def _classify_item(sub_id: str, title: str, bb_url: str,
                   desc_text: str, desc_html: str,
                   files: list, inline_imgs: list, ext_urls: list,
                   upload_url: str, video_url: str,
                   content_link: str = "") -> Item:
    """
    Classify an item into the correct Item subclass.

    Detection priority:
      homework  — has uploadAssignment upload_url
      video     — has iframe video_url
      file      — has bbcswebdav file links
      folder    — has content_link to another BB page
      inline    — has inline images
      link      — has external URLs
      text      — has description text
      unknown   — nothing detectable
    """
    if upload_url:
        return HomeworkItem(sub_id, title, bb_url, desc_text, desc_html,
                           files=files, submission_count=0, deadline="")
    if video_url:
        return VideoItem(sub_id, title, bb_url, desc_text, desc_html,
                        video_url=video_url)
    if files:
        return FileItem(sub_id, title, bb_url, desc_text, desc_html, files=files)
    if content_link:
        return FolderItem(sub_id, title, content_link, desc_text, desc_html)
    if inline_imgs:
        return InlineItem(sub_id, title, bb_url, desc_text, desc_html,
                          inline_imgs=inline_imgs)
    if ext_urls:
        return LinkItem(sub_id, title, bb_url, desc_text, desc_html, ext_urls=ext_urls)
    if desc_text:
        return TextItem(sub_id, title, bb_url, desc_text, desc_html)
    return UnknownItem(sub_id, title, bb_url, desc_text, desc_html)


def _html_to_text(html: str) -> str:
    """Strip HTML tags, decode entities, and clean whitespace."""
    if not html:
        return ""
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<(br|p|li|div|h[1-6])[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', '', html)
    html = html.replace('\xa0', ' ').replace('&nbsp;', ' ')
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&quot;', '"').replace('&#39;', "'")
    html = re.sub(r' {2,}', ' ', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()
