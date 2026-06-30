# Items - BB item type hierarchy
"""
Item classes for all Blackboard content item types.
Each item represents a sub-element within a BB content page.
"""
import re
import urllib.parse
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path as _Path
from typing import List, Optional, Tuple

# China timezone (UTC+8) for deadline comparisons
CHINA_TZ = timezone(timedelta(hours=8))

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_deadline(s) -> Optional[datetime]:
    """
    Parse a deadline string in any of these formats:
      - ISO 8601: "2026-05-12T23:59:00+08:00" or "2026-05-12T23:59:00"
      - Chinese full: "2026年5月12日 23:59" or "2026年5月12日23:59"
      - Chinese date only: "2026年5月12日" (interpreted as end-of-day, 23:59:59)
      - English: "11:59pm, Jun.10th, Wed., Week 16"
      - English (date-only-ish): "Jun.10th, 11:59pm"
      - English with year: "Jun.10th, 2026 11:59pm" or "Jun.10 2026 11:59 PM"
      - Optional "Due date:" / "Due:" / "Deadline:" prefix is ignored

    If the year is not present in the string, defaults to the current year;
    if the parsed date is more than 6 months in the past, assumes next year.
    (Catches January deadlines that are actually next-year.)

    Returns:
        datetime (tz-aware if input had tz, naive if not), or None if unparseable.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    # Try ISO 8601 first (handles both naive and tz-aware)
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    # Chinese full: "2026年5月12日 23:59" or "2026年5月12日23:59"
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", s)
    if m:
        try:
            y, mo, d, h, mi = (int(g) for g in m.groups())
            return datetime(y, mo, d, h, mi, tzinfo=CHINA_TZ)
        except ValueError:
            return None
    # Chinese date only — interpret as end of day
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        try:
            y, mo, d = (int(g) for g in m.groups())
            return datetime(y, mo, d, 23, 59, 59, tzinfo=CHINA_TZ)
        except ValueError:
            return None
    # English: "11:59pm, Jun.10th, Wed., Week 16" or "Jun.10 11:59 PM"
    # Strip optional leading label.
    s2 = re.sub(
        r"^\s*(?:due\s*date|deadline|due|closes?|closes\s*on|open\s*until)\s*[:\-]?\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # Find time HH:MM with optional am/pm
    tm = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?", s2, re.IGNORECASE)
    # Find month + day (with optional ordinal suffix and optional year).
    # Handles: "Jun.10th", "Jun 10", "Jun 10th", "Sept. 1, 2026"
    dm = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s*"
        r"(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:[,\s]+(\d{4}))?",
        s2,
        re.IGNORECASE,
    )
    if tm and dm:
        try:
            h = int(tm.group(1))
            mi = int(tm.group(2))
            ampm = (tm.group(3) or "").lower().rstrip(".")
            mon = _MONTH_ABBR[dm.group(1).lower()]
            d = int(dm.group(2))
            year_explicit = dm.group(3)
            # 12-hour → 24-hour
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            elif not ampm:
                # No am/pm — assume 24h if hour <= 23, else leave as-is.
                pass
            # Year: explicit > current > next year if more than 6mo in past
            now = datetime.now(CHINA_TZ)
            if year_explicit:
                y = int(year_explicit)
            else:
                y = now.year
                try:
                    candidate = datetime(y, mon, d, h, mi, tzinfo=CHINA_TZ)
                    if (now - candidate).days > 180:
                        y += 1
                except ValueError:
                    pass
            return datetime(y, mon, d, h, mi, tzinfo=CHINA_TZ)
        except (ValueError, KeyError):
            return None
    return None


def _check_late_risk(deadline_str: str, *, force_late: bool = False) -> None:
    """Emit a UserWarning if `deadline_str` is in the past.

    This is the late-submission guard: when creating a new attempt on an
    assignment whose deadline has already passed, we want the user to
    know they're submitting late — past-deadline attempts are typically
    recorded as LATE in BB and may be penalized by the instructor.

    Pass `force_late=True` to suppress the warning (e.g. when the user
    has explicitly acknowledged the risk).

    Silently does nothing if:
      - deadline_str is empty or None (can't determine)
      - deadline_str is unparseable (don't false-positive)
    """
    if force_late:
        return
    ddl = _parse_deadline(deadline_str)
    if ddl is None:
        return
    # Normalize to CHINA_TZ for comparison (handle naive datetimes as CST)
    if ddl.tzinfo is None:
        ddl = ddl.replace(tzinfo=CHINA_TZ)
    now = datetime.now(CHINA_TZ)
    if ddl < now:
        delta = now - ddl
        warnings.warn(
            f"LATE SUBMISSION RISK: deadline {deadline_str!r} ({ddl.isoformat()}) "
            f"is in the past (now {now.isoformat()}, "
            f"{delta} after deadline). This will create a new attempt as a LATE "
            f"submission. Set force_late=True to suppress.",
            UserWarning,
            stacklevel=3,
        )


# ─────────────────────────────────────────────────────────────────────────
# BB session helper for live discovery (used by HomeworkItem.from_submission_page)
# ─────────────────────────────────────────────────────────────────────────

_BB_BASE = "https://bb.sustech.edu.cn"


def _bb_session_for_discovery():
    """Return a fresh requests.Session with current BB cookies.

    Mirrors sustech_survival.bb.submit_rest._bb_session() — each call creates
    a new session so cookies don't collide between separate BB REST calls
    (BB rotates JSESSIONID on every request and the cookiejar would otherwise
    keep BOTH the old and new values).

    Auth model: BBAuth is a per-subclass singleton (see Authorizer.__new__).
    If the in-memory session is empty (e.g. fresh interpreter, or a script
    that never called refresh), we refresh() once here so the user doesn't
    have to remember. If the in-memory session is non-empty, we trust it
    (it's been validated by check() or populated by an explicit refresh).
    """
    import requests
    from sustech_survival.sso import BBAuth
    auth = BBAuth()
    # Refresh only if the in-memory cache is empty. We don't probe+refresh
    # on every call — that would do a full CAS login on every from_submission_page
    # call, which is slow and unnecessary.
    if not auth.session_cache:
        if not auth.refresh():
            raise RuntimeError(
                "BB auth not initialized and refresh() failed — re-login required"
            )
    sess = requests.Session()
    sess.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    for c in auth.session.cookies:
        if c.value:
            sess.cookies.set(c.name, c.value, domain=".bb.sustech.edu.cn", path="/")
    return sess


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

    def fmt_desc(self, max_len=38) -> str:
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
        desc = self.fmt_desc()
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
        desc = self.fmt_desc()
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

    @classmethod
    def from_submission_page(cls, course_id: str, content_id: str,
                            group_id: str = "") -> "HomeworkItem":
        """Build a HomeworkItem from the live BB uploadAssignment page.

        This is the SAFE way to construct a HomeworkItem for real submissions
        — it extracts the title and deadline from the actual page BB shows
        to students. Manual construction (e.g. ``HomeworkItem(sub_id=...,
        title="HW1", deadline="...")``) is fragile: the title can be wrong
        and the deadline is often only on the submission page, not in the
        description body.

        Args:
            course_id: numeric course id (e.g. "8328")
            content_id: numeric content id (e.g. "610821")
            group_id: BB group_id (usually empty string; pass through if known)

        Returns:
            A HomeworkItem with title and deadline populated from the page.
            deadline is in Chinese format ("2026年5月12日 23:59") that
            _parse_deadline() handles natively.

        Raises:
            RuntimeError: if BB auth fails or the page can't be fetched

        Example:
            >>> hw = HomeworkItem.from_submission_page("8328", "610821")
            >>> hw.deadline
            '2026年5月12日 23:59'
            >>> ok, msg = hw.submit("/path/to/report.pdf", dry_run=True)
        """
        sess = _bb_session_for_discovery()
        url = (
            f"{_BB_BASE}/webapps/assignment/uploadAssignment"
            f"?action=newAttempt"
            f"&content_id=_{content_id}_1"
            f"&course_id=_{course_id}_1"
            f"&group_id={group_id}"
        )
        r = sess.get(url, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(
                f"GET {url} returned {r.status_code} — "
                f"check BB session and course/content ids"
            )
        html = r.text

        # Title: from <title>Upload Assignment: TITLE</title>
        title_match = re.search(
            r'<title>Upload Assignment:\s*(.+?)</title>', html
        )
        title = title_match.group(1).strip() if title_match else ""

        # Deadline: from "到期日期\n2026年5月12日 23:59" (Chinese format)
        # OR from English "Due date: 11:59pm, Jun.10th, Wed., Week 16"
        # OR from "due on Jun. 10th" in the title fragment.
        deadline = ""
        cn_match = re.search(
            r'到期日期\s*\n?\s*(\d{4}年\d{1,2}月\d{1,2}日[^\n<]*)',
            html,
        )
        if cn_match:
            deadline = cn_match.group(1).strip()
        else:
            # Try "Due date: ..." label
            en_match = re.search(
                r'(?:Due\s*date|Deadline)\s*:\s*'
                r'(\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?'
                r'[^\n<]*?\d{1,2}(?:st|nd|rd|th)?[^\n<]*)',
                html,
                re.IGNORECASE,
            )
            if en_match:
                deadline = en_match.group(1).strip()
            else:
                # Last resort: "due on Mon. Dth" from title fragment
                title_due = re.search(
                    r'due\s+on\s+'
                    r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s*\d{1,2}(?:st|nd|rd|th)?)',
                    html,
                    re.IGNORECASE,
                )
                if title_due:
                    deadline = "23:59, " + title_due.group(1).strip()

        return cls(
            sub_id=f"_{content_id}_1",
            title=title,
            bb_url=url,
            content_id=content_id,
            course_id=course_id,
            group_id=group_id,
            deadline=deadline,
        )

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

    def submit(self, file_path: str, target_name: str | None = None,
               dry_run: bool = False, skip_dedup: bool = True,
               headless: bool = True,
               force_late: bool = False) -> tuple:
        """High-level submit: hand a file to BB for this assignment.

        Uses the Playwright-driven path (see ``sustech_survival.bb.submit``).
        For a no-browser REST path, use ``HomeworkItem.submit_rest()`` instead.

        Thin wrapper around ``sustech_survival.bb.submit.submit_assignment``.
        Pre-renames the file to ``target_name`` on disk (via the underlying
        primitive's staging logic) so BB records the correct basename in
        ``newFile_table`` — no JS-side rename, no duplicate rows.

        Args:
            file_path: absolute path to the local PDF
            target_name: on-disk basename BB should show.
                Defaults to file_path's basename.
            dry_run: stop after the file is in the table, do NOT click submit
            skip_dedup: bypass prior-attempt dedup check
            headless: Playwright headless flag
            force_late: if True, suppress the late-submission warning even when
                the deadline is in the past. Use when you've explicitly decided
                a late attempt is acceptable.

        Returns:
            ``(ok, message)`` — message contains the confirmation UUID on
            success, or ``"DRY-RUN: rows=N, link_titles=[...]"`` if dry-run.

        Late-submission safety: if ``self.deadline`` is set and in the past,
        emits a ``UserWarning`` before the actual submit so the user knows
        they're creating a late attempt. Skipped on dry_run (since no real
        attempt is made) and on force_late=True.

        Example:
            >>> hw = HomeworkItem(sub_id="x", title="HW1",
            ...                   course_id="8221", content_id="626838",
            ...                   deadline="2026-05-12T23:59:00+08:00")
            >>> ok, msg = hw.submit(
            ...     file_path="/tmp/hw15.pdf",
            ...     target_name="<SID>-<NAME>-Experiment 15.pdf",
            ...     dry_run=True,
            ... )
        """
        from pathlib import Path
        target = target_name or Path(file_path).name

        # Late-submission safety check (skip on dry_run, suppress with force_late)
        if not dry_run and self.deadline:
            _check_late_risk(self.deadline, force_late=force_late)

        # Lazy import to avoid circular dependency (items.py → submit.py)
        from sustech_survival.bb.submit import submit_assignment
        result = submit_assignment(
            self.course_id,                 # positional
            self.content_id,                # positional
            [file_path],                    # positional
            name_override=target,           # kwarg
            skip_dedup=skip_dedup,          # kwarg
            dry_run=dry_run,                # kwarg
            headless=headless,              # kwarg
        )
        # Pass through the SubmitResult directly. CLI / agent callers can
        # do `if result:` for truthy check, `result.is_duplicate` for the
        # dedup case, or `result.message` for the human-readable summary.
        return result

    def submit_rest(self, file_path: str, target_name: str | None = None,
                    dry_run: bool = False, skip_dedup: bool = True,
                    force_late: bool = False) -> tuple:
        """High-level submit (REST path, no Playwright). Hand a file to BB.

        This is the no-browser alternative to ``submit()``. Same end-state
        (a new attempt with the file attached) but uses pure HTTP requests
        — no headless Chromium launch, no JS handlers, no DOM manipulation.

        How it works:
          1. GET the upload form (parses hidden fields + CSRF nonce)
          2. Add BB's file-picker fields (see javascript/ngui/widget.js)
          3. POST the form as multipart with the file as newFile_LocalFile0
          4. Parse BB's JSON response for destinationUrl

        Args:
            file_path: absolute path to the local file
            target_name: on-disk basename BB should show. Defaults to
                file_path's basename. The file is staged under this name
                in $TMPDIR/bb_submits/ so BB records it as the displayed
                filename in the attempt receipt.
            dry_run: if True, GET the form + simulate the POST, but don't
                actually submit. Returns (True, "DRY-RUN: ...").
            skip_dedup: no-op for the REST path (REST doesn't do a per-
                attempt dedup like Playwright does). Kept for API parity
                with ``submit()``.
            force_late: if True, suppress the late-submission warning even
                when the deadline is in the past.

        Returns:
            ``(ok, message)`` — message contains BB's destinationUrl on
            success, or ``"DRY-RUN: ..."`` if dry-run, or an error string
            starting with the failure mode (e.g. "File not found:",
            "Form POST returned 500:").

        Late-submission safety: identical to ``submit()`` — emits a
        ``UserWarning`` if ``self.deadline`` is in the past. Suppressed
        with ``force_late=True`` or on dry_run.

        Example:
            >>> hw = HomeworkItem.from_submission_page("8328", "610821")
            >>> ok, msg = hw.submit_rest(
            ...     file_path="/tmp/hw.pdf",
            ...     target_name="<SID>-<NAME>-Experiment 5.pdf",
            ...     dry_run=True,
            ... )
        """
        from pathlib import Path
        target = target_name or Path(file_path).name

        # Late-submission safety check (skip on dry_run, suppress with force_late)
        if not dry_run and self.deadline:
            _check_late_risk(self.deadline, force_late=force_late)

        # Lazy import to avoid circular dependency (items.py → submit_rest.py)
        from sustech_survival.bb.submit_rest import submit_assignment_rest
        return submit_assignment_rest(
            self.course_id,                 # positional
            self.content_id,                # positional
            file_path,                      # positional
            name_override=target,           # kwarg
            dry_run=dry_run,                # kwarg
            skip_dedup=skip_dedup,          # kwarg (no-op for REST)
        )

    def to_row(self) -> str:
        deadline_str = self.deadline or "-"
        sub_count = str(self.submission_count)
        ids_str = f"{self.course_id}/{self.content_id}" if self.course_id else self.sub_id
        desc = self.fmt_desc()
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

    def fetch_attempts(self):
        """Fetch attempt details via REST API. Cached on first call."""
        if hasattr(self, 'attempts_cached'):
            return self.attempts_cached

        course_id = getattr(self, 'course_id', None)
        content_id = getattr(self, 'content_id', None)
        if not (course_id and content_id):
            self.attempts_cached = []
            return []

        try:
            from sustech_survival.sso import BBAuth
            auth = BBAuth(skill_dir=str(BB_DIR.parent.parent.parent))
            ok, reason = auth.ensure()
            if not ok:
                self.attempts_cached = []
                return []
            sess = auth.session

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
                self.attempts_cached = []
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
            self.attempts_cached = results
            return results
        except Exception:
            self.attempts_cached = []
            return []

    def __str__(self) -> str:
        """Full status string including submission history, grade, and feedback."""
        lines = [self.title]
        if getattr(self, 'course_id', None) and getattr(self, 'content_id', None):
            lines.append(f"   course={self.course_id} content={self.content_id}")
        lines.append(f"   deadline: {self.deadline or 'not set'}")
        if self.files:
            lines.append(f"   attachments: {', '.join(f[0] for f in self.files)}")

        attempts = self.fetch_attempts()
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
        desc = self.fmt_desc()
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
        desc = self.fmt_desc()
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
        desc = self.fmt_desc()
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
        desc = self.fmt_desc()
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
        desc = self.fmt_desc()
        return (f"{self.sub_id}\t{self.TYPE}\t{self.title[:40]}\t"
                f"0\t0\t-\t-\t{desc}")


def classify_item(sub_id: str, title: str, bb_url: str,
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


def html_to_text(html: str) -> str:
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
