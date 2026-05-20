# authlib — SUSTech institutional authorizers
# Re-export all auth modules so `from sustech_survival.sso.authlib import wos` works.
# Importing any authlib subpackage triggers its register_auth() call at module load.

from . import ieee, jstor, pubmed
from . import acs, rsc, wiley, springer, scopus
from . import bb, tis, lib, wos  # noqa: F401

__all__ = ["bb", "tis", "lib", "wos", "ieee", "jstor", "pubmed", "acs", "rsc", "wiley", "springer", "scopus"]