# =============================================================================
# SUSTech Blackboard (BB) — CAS Authorizer
# =============================================================================

from pathlib import Path
from ..providers.cas import CASAuthorizer
from ..base import register_auth

BB_BASE = "https://bb.sustech.edu.cn"
BB_SSO = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"


class BBAuth(CASAuthorizer):
    BASE_URL = BB_BASE
    SERVICE_URL = BB_SSO
    SESSION_SUBDIR = "bb"
    # SUBMIT_VALUE = "\u63d0\u4ea4"  # Chinese submit — inherited from CASAuthorizer default

    @property
    def submodule_dir(self):
        return self.skill_root / "bb"

    @property
    def session_file(self):
        return self.skill_root / "bb" / "session.json"

    @property
    def creds_file(self):
        return self.skill_root / "bb" / "credentials.txt"


_auth = BBAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("bb", _auth)