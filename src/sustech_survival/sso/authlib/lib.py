# =============================================================================
# SUSTech Library (Primo) — CAS Authorizer
# =============================================================================

from pathlib import Path
from ..providers.cas import CASAuthorizer
from ..base import register_auth

LIB_BASE = "https://sustc.primo.exlibrisgroup.com.cn"
LIB_SSO = "https://sustc.primo.exlibrisgroup.com.cn/infra/casRedirect?ctx=/primaws"


class LibAuth(CASAuthorizer):
    BASE_URL = LIB_BASE
    SERVICE_URL = LIB_SSO
    SESSION_SUBDIR = "lib"

    @property
    def submodule_dir(self):
        return self.skill_root / "lib"

    @property
    def session_file(self):
        return self.skill_root / "lib" / "session.json"

    @property
    def creds_file(self):
        return self.skill_root / "credentials.txt"

    @property
    def _domain(self):
        return "sustc.primo.exlibrisgroup.com.cn"


_auth = LibAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("lib", _auth)