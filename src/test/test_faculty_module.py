"""Tests for sustech_survival.faculty — verify module + parser unit-level.

These run against fixtures only (no network), so they don't make the skill
slower or fragile. Live API behavior is verified manually via the CLI.

To run:
    /Users/dumix/.hermes/hermes-agent/venv/bin/python -m pytest \
        src/test/test_faculty_module.py -v
"""
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent
sys.path.insert(0, str(SRC))


def test_imports():
    """The new public surface: `faculty` client + `Faculty` + `DEPARTMENTS`."""
    from sustech_survival.faculty import faculty, Faculty, DEPARTMENTS
    assert len(DEPARTMENTS) >= 50, f"expected 50+ depts, got {len(DEPARTMENTS)}"
    assert "材料科学与工程系" in DEPARTMENTS
    assert "数学系" in DEPARTMENTS
    # client surface
    for m in ("list", "get", "search", "render"):
        assert hasattr(faculty, m) and callable(getattr(faculty, m)), f"faculty.{m} missing"


def test_faculty_dataclass():
    """Faculty dataclass should accept all fields and serialize via to_dict/to_markdown."""
    from sustech_survival.faculty import Faculty
    f = Faculty(
        slug="test",
        name="Test User",
        title="教授",
        department="测试系",
        email="test@sustech.edu.cn",
        research_interests=["AI", "ML"],
        education=["2010-2014 测试大学 学士"],
        work_history=["2014-现在 测试大学 教授"],
    )
    d = f.to_dict()
    assert d["slug"] == "test"
    assert d["name"] == "Test User"
    assert d["email"] == "test@sustech.edu.cn"
    assert "AI" in d["research_interests"]
    md = f.to_markdown()
    assert "slug: test" in md
    assert "name: Test User" in md
    assert "AI" in md
    assert "## Education" in md
    assert "## Research Interests" in md


def test_search_metadata_fields():
    """Faculty should carry relevance_score + matched_fields for search results."""
    from sustech_survival.faculty import Faculty
    f = Faculty(slug="x", name="Test", research_interests=["quantum"])
    assert f.relevance_score is None
    assert f.matched_fields == []
    # simulate search
    f.relevance_score = 42
    f.matched_fields = ["name", "research_interests"]
    d = f.to_dict()
    assert d["relevance_score"] == 42
    assert d["matched_fields"] == ["name", "research_interests"]
def test_parser_index_cards_with_fixture():
    """IndexCard.list_from_index_html should handle a real ?ajax=users HTML chunk."""
    from sustech_survival.faculty import IndexCard
    sample = """
    <li><a href="/alexander/" target="_blank">
        <div class="teacher_iteam">
            <div class="teacher_top">
                <div class="teacher_tx" style="background:url(http://example.com/a.jpg)"></div>
            </div>
            <div class="teacher_cont">
                <h2>Alexander Kurganov</h2>
                <span></span>
                <h3></h3>
                <p>数学系</p>
            </div>
        </div>
    </a></li>
    <li><a href="/andrewh/" target="_blank">
        <div class="teacher_iteam">
            <div class="teacher_top">
                <div class="teacher_tx" style="background:url(http://example.com/b.jpg)"></div>
            </div>
            <div class="teacher_cont">
                <h2>Andrew Hutchins</h2>
                <span></span>
                <h3>副教授</h3>
                <p>生物系</p>
            </div>
        </div>
    </a></li>
    <li><a href="/li/" target="_blank">
        <div class="teacher_iteam">
            <div class="teacher_top">
                <div class="teacher_tx" style="background:url(http://example.com/c.jpg)"></div>
            </div>
            <div class="teacher_cont">
                <h2>李四</h2>
                <span></span>
                <h3></h3>
                <p>材料科学与工程系</p>
            </div>
        </div>
    </a></li>
    """
    cards = IndexCard.list_from_index_html(sample)
    assert len(cards) == 3
    assert cards[0].slug == "alexander"
    assert cards[0].name == "Alexander Kurganov"
    assert cards[0].department == "数学系"
    assert cards[1].title == "副教授"
    assert cards[2].name == "李四"


def test_parser_profile_page_with_fixture():
    """Faculty.from_profile_html should extract fields from a minimal profile HTML."""
    from sustech_survival.faculty import Faculty
    sample = """
    <html><body>
    <div class="teachers_info">
        <dl>
            <dt class="bgimgdt" style="background-image: url(http://example.com/p.jpg);">
                <img class="opavatarimg" src="http://example.com/p.jpg" />
            </dt>
        </dl>
    </div>
    <div class="teachers_desc">
        <h2 class="t_name">张三</h2>
        <em class="t_zw">教授</em>
        <span class="t_xy">物理系</span>
        <div class="t_descs"><p>张三是一个测试用户。</p></div>
    </div>
    <div class="js_background">
        <h3>个人简介</h3>
        <div class="jsjj_ct">
            <p><strong>教育经历：</strong></p>
            <p>2010-2014 清华大学 学士</p>
            <p><strong>工作经历：</strong></p>
            <p>2014-现在 清华大学 教授</p>
            <p><strong>目前研究兴趣：</strong></p>
            <p><strong>量子计算</strong></p>
            <p>量子算法的设计与实现</p>
        </div>
    </div>
    <div>
        <p>联系地址  </p>
        <p>北京市海淀区</p>
    </div>
    <div>
        <p>办公电话  </p>
        <p>010-12345678</p>
    </div>
    <div>
        <p>电子邮箱 </p>
        <p>zhangsan@sustech.edu.cn</p>
    </div>
    </body></html>
    """
    f = Faculty.from_profile_html(sample, slug="zhangsan")
    assert f.slug == "zhangsan"
    assert f.name == "张三"
    assert f.title == "教授"
    assert f.department == "物理系"
    assert f.email == "zhangsan@sustech.edu.cn"
    assert f.phone == "010-12345678"
    assert f.office == "北京市海淀区"
    assert f.photo_url == "http://example.com/p.jpg"
    assert "测试用户" in (f.biography or "")
    assert f.education == ["2010-2014 清华大学 学士"]
    assert f.work_history == ["2014-现在 清华大学 教授"]
    assert any("量子计算" in r for r in f.research_interests)
    assert any("量子算法" in r for r in f.research_interests)


def test_faculty_from_index_card_promotion():
    """Faculty.from_index_card should preserve all the card fields."""
    from sustech_survival.faculty import Faculty, IndexCard
    card = IndexCard(slug="chengc", name="程 春", title="教授",
                      department="材料科学与工程系",
                      photo_url="http://x/p.jpg",
                      profile_url="https://faculty.sustech.edu.cn/?tagid=chengc&lang=zh&go=2")
    f = Faculty.from_index_card(card)
    assert f.slug == "chengc"
    assert f.name == "程 春"
    assert f.title == "教授"
    assert f.department == "材料科学与工程系"
    assert f.photo_url == "http://x/p.jpg"
    # research fields are still empty until profile is fetched
    assert f.research_interests == []
    assert f.email is None