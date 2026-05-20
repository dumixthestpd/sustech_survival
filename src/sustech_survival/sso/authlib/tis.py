# =============================================================================
# SUSTech Teaching Information System (TIS) — CAS Authorizer
# =============================================================================

from pathlib import Path
from ..providers.cas import CASAuthorizer
from ..base import register_auth

TIS_BASE = "https://tis.sustech.edu.cn"
TIS_SSO = "https://tis.sustech.edu.cn/cas"


class TISAuth(CASAuthorizer):
    BASE_URL = TIS_BASE
    SERVICE_URL = TIS_SSO
    SESSION_SUBDIR = "tis"
    XHR_MODE = True
    SUBMIT_VALUE = ""  # TIS CAS has no submit button value in POST body

    @property
    def submodule_dir(self):
        return self.skill_root / "tis"

    @property
    def session_file(self):
        return self.skill_root / "tis" / "session.json"

    @property
    def creds_file(self):
        return self.skill_root / "credentials.txt"


_auth = TISAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("tis", _auth)