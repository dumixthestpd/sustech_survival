# =============================================================================
# SUSTech Blackboard (BB) — CAS Authorizer
# =============================================================================

from pathlib import Path
from ..providers.cas import CASAuthorizer
from ..authorizer import register_auth

BB_BASE = "https://bb.sustech.edu.cn"
BB_SSO = "https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp"


class BBAuth(CASAuthorizer):
    BASE_URL = BB_BASE
    SERVICE_URL = BB_SSO
    SESSION_SUBDIR = "bb"


_auth = BBAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("bb", _auth)