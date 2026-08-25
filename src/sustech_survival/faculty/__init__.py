"""
sustech_survival.faculty — Live SUSTech faculty directory query.

ONE client (`faculty`). Four operations. Zero local data.

    from sustech_survival.faculty import faculty, Faculty

    cards = faculty.list("材料科学与工程系")                    # lightweight
    full  = faculty.list("材料科学与工程系", full=True)         # with research interests

    chengc = faculty.get("chengc")                           # one profile
    print(chengc.to_markdown())                              # AI-readable

    hits = faculty.search("电池", dept="材料科学与工程系")    # sorted by relevance
    for f in hits:
        print(f"  {f.name}  score={f.relevance_score}  matched={f.matched_fields}")

    print(faculty.departments)                               # 50+ dept names
"""
from .faculty import faculty, FacultyClient, DEPARTMENTS
from .schema import Faculty, IndexCard

__all__ = [
    "faculty",          # the singleton client — start here
    "FacultyClient",    # class, for custom configs (delay/workers)
    "Faculty",          # record type (with parsing classmethods)
    "IndexCard",        # lightweight record (with parsing classmethod)
    "DEPARTMENTS",      # 50+ dept names
]
