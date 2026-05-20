# =============================================================================
# SUSTech Library (Primo) — CAS Authorizer
# =============================================================================

from pathlib import Path
from ..providers.cas import CASAuthorizer
from ..authorizer import register_auth

LIB_BASE = "https://sustc.primo.exlibrisgroup.com.cn"
LIB_SSO = "https://sustc.primo.exlibrisgroup.com.cn/infra/casRedirect?ctx=/primaws"


class LibAuth(CASAuthorizer):
    BASE_URL = LIB_BASE
    SERVICE_URL = LIB_SSO
    SESSION_SUBDIR = "lib"


_auth = LibAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("lib", _auth)