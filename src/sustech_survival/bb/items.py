# Items - BB item type hierarchy
"""
Item classes for all Blackboard content item types.
Each item represents a sub-element within a BB content page.
"""

import re
import urllib.parse
from pathlib import Path as _Path
from typing import List, Tuple

BB_DIR = _Path(__file__).resolve()  # items.py is at depth 5 in skill_root

BB_BASE = "https://bb.sustech.edu.cn"


class Item:
    """
    Base class for all BB item types.

    All items share:
      sub_id, title, type (item type string), bb_url,
      description, description_html

    Subclasses:
      FileItem      - downloadable files (PDF, doc, etc.)
      VideoItem     - embedded video player (iframe)
      HomeworkItem  - assignment with uploadAssignment link
      InlineItem    - inline images embedded in page
      LinkItem      - external URL references
      TextItem      - description text only
      UnknownItem   - could not determine type
    """

    TYPE = "unknown"
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



# ── Item subclasses ──
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
                 files: list = None, submission_count: int = 0, deadline: str = "",
                 content_id: str = "", course_id: str = "", group_id: str = ""):
        super().__init__(sub_id, title, bb_url, description, description_html)
        self.files = files or []
        self.submission_count = submission_count
        self.deadline = deadline
        self.content_id = content_id  # BB content_id (e.g. "610795")
        self.course_id = course_id    # BB course numeric ID (e.g. "8328")
        self.group_id = group_id      # BB group_id (usually empty string)

    @property
    def has_attachment(self) -> bool:
        return bool(self.files)

    def submission_url(self, action="newAttempt") -> str:
        """Build the submission URL for this homework item.
        Args:
            action: 'newAttempt' (default), 'view', or 'submit'
        Returns URL string ready to open in browser.
        """
        if not (self.content_id and self.course_id):
            return ""
        return (
            f"{BB_BASE}/webapps/assignment/uploadAssignment"
            f"?action={action}&content_id=_{self.content_id}_1"
            f"&course_id=_{self.course_id}_1&group_id={self.group_id or ''}"
        )

    def to_row(self) -> str:
        deadline_str = self.deadline or "-"
        sub_count = str(self.submission_count)
        ids_str = f"{self.course_id}/{self.content_id}" if self.course_id else self.sub_id
        desc = self._fmt_desc()
        return (f"{ids_str}\t{self.TYPE}\t{self.title[:40]}\t"
                f"{len(self.files)}\t0\t{sub_count}\t{deadline_str}\t{desc}")

    def to_markdown(self) -> str:
        lines = [f"## {self.title}\n"]
        if self.course_id and self.content_id:
            lines.append(f"**`course={self.course_id} content={self.content_id}`**\n")
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
                f"\n**[Homework Submission]** - "
                f"{self.submission_count} submission(s) made.{deadline_note}"
            )
        else:
            lines.append(
                f"\n**[Homework Submission]** - not submitted yet."
                f"{deadline_note}"
            )
        return "\n".join(lines)

    def _fetch_attempts(self):
        """Fetch attempt details via REST API. Cached on first call."""
        if hasattr(self, '_attempts_cached'):
            return self._attempts_cached

        course_id = getattr(self, 'course_id', None)
        content_id = getattr(self, 'content_id', None)
        if not (course_id and content_id):
            self._attempts_cached = []
            return []

        try:
            from sustech_survival.sso import BBAuth
            auth = BBAuth(skill_dir=str(BB_DIR.parent.parent.parent))
            raw = auth.load()
            import requests
            sess = requests.Session()
            for name, value in raw.items():
                sess.cookies.set(name, value, domain=".bb.sustech.edu.cn", path="/")

            BB_BASE = "https://bb.sustech.edu.cn"

            # 1. Find the grade column ID for this content item
            bid = "_" + course_id + "_1"
            cid = "_" + content_id + "_1"
            cols_data = sess.get(
                f"{BB_BASE}/learn/api/public/v1/courses/{bid}/gradebook/columns"
                f"?_fields=id,contentId",
                timeout=10
            ).json()
            col_id = None
            for col in cols_data.get("results", []):
                if col.get("contentId") == cid:
                    col_id = col.get("id")
                    break
            if not col_id:
                self._attempts_cached = []
                return []

            # 2. Get attempts for this column
            attempts_data = sess.get(
                f"{BB_BASE}/learn/api/public/v1/courses/{bid}/gradebook/columns/{col_id}/attempts",
                timeout=10
            ).json()

            results = []
            for attempt in attempts_data.get("results", []):
                results.append({
                    'anum': 1,
                    'ts': attempt.get('created', ''),
                    'files': [],
                    'graded': attempt.get('status') == 'Completed',
                    'score': attempt.get('score'),
                    'grade': attempt.get('score'),  # same field in this API
                    'feedback': attempt.get('feedback', ''),
                })
            self._attempts_cached = results
            return results
        except Exception:
            self._attempts_cached = []
            return []

    def __str__(self) -> str:
        """Full status string including submission history, grade, and feedback."""
        lines = [self.title]
        if getattr(self, 'course_id', None) and getattr(self, 'content_id', None):
            lines.append(f"   course={self.course_id} content={self.content_id}")
        lines.append(f"   deadline: {self.deadline or 'not set'}")
        if self.files:
            lines.append(f"   attachments: {', '.join(f[0] for f in self.files)}")

        attempts = self._fetch_attempts()
        if not attempts:
            lines.append("   status: not submitted")
        else:
            for a in attempts:
                graded_mark = '[GRADED]' if a['graded'] else '[UNGRADED]'
                grade_str = f" {a['score']}/{a['grade']}" if a['score'] and a['grade'] else f" {a['grade']}/100" if a['grade'] else ''
                files_str = ', '.join([f"'{n}'" for n, _ in a['files']]) or 'no files'
                feedback = a.get('feedback') or ''
                feedback_preview = (feedback[:60] + '...') if len(feedback) > 60 else feedback
                lines.append(f"   {graded_mark} attempt {a['anum']}{grade_str} -- {files_str}")
                if feedback_preview:
                    lines.append(f"        feedback: {feedback_preview}")
        return chr(10).join(lines)


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


def _classify_item(sub_id: str, title: str, bb_url: str,
                   desc_text: str, desc_html: str,
                   files: list, inline_imgs: list, ext_urls: list,
                   upload_url: str, video_url: str,
                   content_link: str = "") -> Item:
    """
    Classify an item into the correct Item subclass.

    Detection priority:
      homework  - has uploadAssignment upload_url
      video     - has iframe video_url
      file      - has bbcswebdav file links
      folder    - has content_link to another BB page
      inline    - has inline images
      link      - has external URLs
      text      - has description text
      unknown   - nothing detectable
    """
    if upload_url:
        # Parse content_id, course_id, group_id from uploadAssignment URL
        # URL format: /webapps/assignment/uploadAssignment?content_id=_610795_1&course_id=_8328_1&group_id=&mode=view
        m_cid = re.search(r'content_id=_(\d+)_1', upload_url)
        m_crs = re.search(r'course_id=_(\d+)_1', upload_url)
        m_grp = re.search(r'group_id=([^&\s"\']*)', upload_url)
        cid = m_cid.group(1) if m_cid else ""
        crs = m_crs.group(1) if m_crs else ""
        grp = urllib.parse.unquote(m_grp.group(1)) if m_grp else ""
        return HomeworkItem(sub_id, title, bb_url, desc_text, desc_html,
                           files=files, submission_count=0, deadline="",
                           content_id=cid, course_id=crs, group_id=grp)
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
