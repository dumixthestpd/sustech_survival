"""
sustech_survival.faculty.schema — Data classes with classmethod constructors.

All parsing lives ON the data classes, not in loose functions. To go from
HTML to a record, call `Faculty.from_profile_html(html, slug)` or
`IndexCard.list_from_index_html(html)`. No HTTP, no I/O — just parsing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from lxml import html as lxml_html
from lxml.html import HtmlElement


# -- Constants ----------------------------------------------------------------

PROFILE_URL_TPL = "https://faculty.sustech.edu.cn/?tagid={slug}&lang=zh&go=2"

EDU_HEADER = "教育经历"
WORK_HEADER = "工作经历"
INTEREST_HEADER = "目前研究兴趣"

# Top-level headers in 个人简介 end with `：</strong></p>` (with colon).
# Sub-bullets inside 研究兴趣 look like `<p><strong>NAME</strong></p>` (NO colon)
# — those are the actual interest items, NOT new sections.
_SECTION_RE = re.compile(
    r'<p>\s*<strong>\s*([^：:]+?)\s*[：:]\s*</strong>\s*</p>(.*?)(?=<p>\s*<strong>[^<]+[：:]\s*</strong>\s*</p>|$)',
    re.DOTALL,
)

# Contact info: <p>LABEL</p> followed by <p>VALUE</p> pair anywhere on the page.
_CONTACT_PAIR_RE = re.compile(
    r'<p>\s*(联系地址|办公电话|电子邮箱|Email|Phone|Office|Tel|Fax)\s*</p>\s*<p[^>]*>\s*([^<]+?)\s*</p>',
    re.IGNORECASE,
)

# Photo URL: dt.bgimgdt style="background-image: url(...)" or img.opavatarimg src="..."
_BGIMG_RE = re.compile(r"url\(([^)]+)\)")


# -- HTML helpers (private, used by classmethods) ----------------------------

def _parse_html(html: str) -> HtmlElement:
    if not html or not html.strip():
        return lxml_html.fragment_fromstring("<html></html>")
    return lxml_html.fromstring(html)


def _text(el: Optional[HtmlElement]) -> str:
    if el is None:
        return ""
    t = el.text_content() if hasattr(el, "text_content") else (el.text or "")
    return re.sub(r"\s+", " ", t).strip()


def _attr(el: Optional[HtmlElement], name: str) -> Optional[str]:
    if el is None:
        return None
    v = el.get(name)
    return v if v else None


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</p>\s*<p[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# -- IndexCard ----------------------------------------------------------------

@dataclass
class IndexCard:
    """Lightweight entry from the ?ajax=users listing — no profile fetch."""
    slug: str
    name: str
    title: Optional[str] = None
    department: Optional[str] = None
    photo_url: Optional[str] = None
    profile_url: str = ""

    @property
    def profile_url_resolved(self) -> str:
        return self.profile_url or PROFILE_URL_TPL.format(slug=self.slug)

    @classmethod
    def list_from_index_html(cls, html: str, default_dept: str = None) -> List["IndexCard"]:
        """Parse a chunk of /?ajax=users HTML into IndexCard list.

        Each card structure (WordPress `nkdgrzy` theme):
            <li> > <a href="/slug/"> > div.teacher_iteam
                div.teacher_tx (style="background:url(<photo>)")
                div.teacher_cont > h2 (name), h3 (title, may be empty), p (dept)
        """
        root = _parse_html(html)
        cards: List[IndexCard] = []
        for a in root.xpath(".//li//a"):
            href = _attr(a, "href") or ""
            m = re.match(r"^/([^/]+)/?$", href.strip())
            if not m:
                continue
            slug = m.group(1)
            if not slug or slug in ("wp-content", "wp-includes", "retrieval", "index.php"):
                continue
            iteams = a.xpath("./div[contains(@class,'teacher_iteam')]")
            if not iteams:
                continue
            iteam = iteams[0]
            # photo
            photo = None
            for tx in iteam.xpath(".//div[contains(@class,'teacher_tx')]"):
                style = _attr(tx, "style") or ""
                sm = _BGIMG_RE.search(style)
                if sm:
                    photo = sm.group(1).strip().strip('"').strip("'")
                    break
            # text
            name = ""
            title = None
            dept = None
            conts = iteam.xpath(".//div[contains(@class,'teacher_cont')]")
            if conts:
                cont = conts[0]
                h2s = cont.xpath("./h2")
                if h2s:
                    name = _text(h2s[0])
                h3s = cont.xpath("./h3")
                if h3s:
                    t = _text(h3s[0])
                    if t:
                        title = t
                ps = cont.xpath("./p")
                if ps:
                    dept = _text(ps[0]) or None
            if not name:
                continue
            cards.append(cls(
                slug=slug,
                name=name,
                title=title,
                department=dept or default_dept,
                photo_url=photo,
                profile_url=PROFILE_URL_TPL.format(slug=slug),
            ))
        return cards

    def to_dict(self) -> dict:
        return asdict(self)


# -- Faculty ------------------------------------------------------------------

@dataclass
class Faculty:
    """One SUSTech faculty member. Constructed from HTML via classmethods,
    or by promotion from an IndexCard via `from_index_card`."""
    slug: str
    name: str = ""
    name_en: Optional[str] = None
    title: Optional[str] = None
    department: Optional[str] = None
    photo_url: Optional[str] = None
    profile_url: str = ""

    # profile-page fields (None / [] until parsed from a profile page)
    email: Optional[str] = None
    phone: Optional[str] = None
    office: Optional[str] = None
    researcher_id: Optional[str] = None
    biography: Optional[str] = None
    education: List[str] = field(default_factory=list)
    work_history: List[str] = field(default_factory=list)
    research_interests: List[str] = field(default_factory=list)
    research_projects: Optional[str] = None
    publications: Optional[str] = None
    other: dict = field(default_factory=dict)

    # search metadata (set by FacultyClient.search; None otherwise)
    relevance_score: Optional[int] = None
    matched_fields: List[str] = field(default_factory=list)

    @property
    def profile_url_resolved(self) -> str:
        return self.profile_url or PROFILE_URL_TPL.format(slug=self.slug)

    @classmethod
    def from_index_card(cls, card: IndexCard) -> "Faculty":
        """Promote a lightweight IndexCard to a Faculty skeleton (no profile data)."""
        return cls(
            slug=card.slug,
            name=card.name,
            title=card.title,
            department=card.department,
            photo_url=card.photo_url,
            profile_url=card.profile_url_resolved,
        )

    @classmethod
    def from_profile_html(
        cls,
        html: str,
        slug: str,
        fallback_name: Optional[str] = None,
        fallback_title: Optional[str] = None,
        fallback_dept: Optional[str] = None,
    ) -> "Faculty":
        """Parse a full /?tagid=<slug> HTML page into a Faculty record.

        Selectors are tied to the WordPress `nkdgrzy` theme.
        """
        root = _parse_html(html)
        fac = cls(
            slug=slug,
            name=fallback_name or "",
            title=fallback_title,
            department=fallback_dept,
            profile_url=PROFILE_URL_TPL.format(slug=slug),
        )

        # name (h2.t_name)
        name_els = root.xpath(".//h2[contains(@class,'t_name')]")
        if name_els:
            fac.name = _text(name_els[0])
        if not fac.name and fallback_name:
            fac.name = fallback_name

        # title (em.t_zw)
        title_els = root.xpath(".//em[contains(@class,'t_zw')]")
        if title_els:
            t = _text(title_els[0])
            if t:
                fac.title = t
        if not fac.title and fallback_title:
            fac.title = fallback_title

        # department (span.t_xy, strip 课题组网站 link text)
        dept_els = root.xpath(".//span[contains(@class,'t_xy')]")
        if dept_els:
            text = _text(dept_els[0])
            text = re.sub(r"课题组网站", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                fac.department = text
        if not fac.department and fallback_dept:
            fac.department = fallback_dept

        # ResearcherID + Google Scholar
        rid_els = root.xpath('.//a[contains(@href,"researcherid.com/rid/")]')
        if rid_els:
            fac.researcher_id = _attr(rid_els[0], "href")
        gs_els = root.xpath('.//a[contains(@href,"scholar.google.com")]')
        if gs_els:
            h = _attr(gs_els[0], "href")
            if h:
                fac.other["google_scholar"] = h

        # biography prose from .t_descs
        bio_els = root.xpath(".//div[contains(@class,'t_descs')]")
        if bio_els:
            prose = _strip_html(str(lxml_html.tostring(bio_els[0], encoding="unicode")))
            if prose and not prose.startswith(EDU_HEADER):
                fac.biography = prose

        # .jsjj_ct — split into sections
        jsjj_els = root.xpath(".//div[contains(@class,'jsjj_ct')]")
        if jsjj_els:
            body_html = str(lxml_html.tostring(jsjj_els[0], encoding="unicode"))
            for m in _SECTION_RE.finditer(body_html):
                header = m.group(1).strip()
                content_html = m.group(2)
                plain = _strip_html(content_html)
                lines = [l.strip() for l in plain.split("\n") if l.strip()]
                if not lines:
                    continue
                if header == EDU_HEADER:
                    fac.education = lines
                elif header == WORK_HEADER:
                    fac.work_history = lines
                elif header == INTEREST_HEADER:
                    fac.research_interests = lines
                else:
                    fac.other.setdefault("sections", {})[header] = lines

        # Contact info: <p>LABEL</p><p>VALUE</p> pairs anywhere on the page
        for m in _CONTACT_PAIR_RE.finditer(html):
            label = m.group(1).strip().lower()
            value = re.sub(r"\s+", " ", m.group(2)).strip()
            if not value:
                continue
            if "电话" in label or "phone" in label or "tel" in label:
                fac.phone = re.sub(r"\s+", "", value)
            elif "邮箱" in label or "email" in label:
                fac.email = value
            elif "地址" in label or "office" in label or "fax" in label:
                fac.office = value

        # Photo URL
        bgdt_els = root.xpath(".//dt[contains(@class,'bgimgdt')]")
        if bgdt_els:
            style = _attr(bgdt_els[0], "style") or ""
            sm = _BGIMG_RE.search(style)
            if sm:
                fac.photo_url = sm.group(1).strip().strip('"').strip("'")
        if not fac.photo_url:
            img_els = root.xpath(".//img[contains(@class,'opavatarimg')]")
            if img_els:
                src = _attr(img_els[0], "src")
                if src:
                    fac.photo_url = src

        return fac

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        """AI-readable per-faculty Markdown with YAML frontmatter."""
        lines: List[str] = []
        lines.append("---")
        lines.append(f"slug: {self.slug}")
        lines.append(f"name: {self.name}")
        if self.name_en:
            lines.append(f"name_en: {self.name_en}")
        if self.title:
            lines.append(f"title: {self.title}")
        if self.department:
            lines.append(f"department: {self.department}")
        if self.email:
            lines.append(f"email: {self.email}")
        if self.phone:
            lines.append(f"phone: {self.phone}")
        if self.office:
            lines.append(f"office: {self.office}")
        if self.researcher_id:
            lines.append(f"researcher_id: {self.researcher_id}")
        if self.photo_url:
            lines.append(f"photo: {self.photo_url}")
        if self.profile_url:
            lines.append(f"profile: {self.profile_url}")
        if self.research_interests:
            lines.append(f"tags: {', '.join(self.research_interests)}")
        if self.relevance_score is not None:
            lines.append(f"relevance_score: {self.relevance_score}")
            lines.append(f"matched_fields: {', '.join(self.matched_fields)}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {self.name}")
        if self.title:
            lines.append(f"**{self.title}** — {self.department or '?'}")
        lines.append("")

        if self.biography:
            lines.append("## Biography")
            lines.append(self.biography)
            lines.append("")

        if self.education:
            lines.append("## Education")
            for e in self.education:
                lines.append(f"- {e}")
            lines.append("")

        if self.work_history:
            lines.append("## Work History")
            for w in self.work_history:
                lines.append(f"- {w}")
            lines.append("")

        if self.research_interests:
            lines.append("## Research Interests")
            for r in self.research_interests:
                lines.append(f"- {r}")
            lines.append("")

        if self.email or self.phone or self.office or self.researcher_id:
            lines.append("## Contact")
            if self.email:
                lines.append(f"- Email: {self.email}")
            if self.phone:
                lines.append(f"- Phone: {self.phone}")
            if self.office:
                lines.append(f"- Office: {self.office}")
            if self.researcher_id:
                lines.append(f"- ResearcherID: {self.researcher_id}")
            lines.append("")
        return "\n".join(lines)
