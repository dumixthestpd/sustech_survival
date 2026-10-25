"""TLS policy for the campus-proxied services.

Campus hosts still speak pre-RFC-5746 TLS, so ``OP_LEGACY_SERVER_CONNECT`` has
to stay on for their pools — that option is the whole reason this adapter
exists. It is *not* a reason to skip certificate validation: CAS credentials
are the master key for BB / TIS / library / PMS / eHall, so a MITM that can
terminate TLS would own the account. Verification is therefore ON by default,
including on proxy pools.

``SUSTECH_TLS_INSECURE=1`` is the explicit escape hatch for the one
environment that genuinely cannot be validated (an intercepting corporate or
lab proxy, a private mirror with a self-signed cert). It is opt-in per process,
never the default, and it is the only way to get the old ``CERT_NONE``
behaviour back.
"""
from __future__ import annotations

import os
import ssl

from requests.adapters import HTTPAdapter

_TRUTHY = {"1", "true", "yes", "on"}


def insecure_mode() -> bool:
    """True when this process opted into unverified TLS."""
    return os.environ.get("SUSTECH_TLS_INSECURE", "").strip().lower() in _TRUTHY


def campus_ssl_context(*, insecure: bool | None = None) -> ssl.SSLContext:
    """The TLS context every campus pool shares.

    Verification is enabled unless ``insecure`` (or ``SUSTECH_TLS_INSECURE``)
    says otherwise; the legacy-renegotiation option is always set.
    """
    if insecure is None:
        insecure = insecure_mode()
    ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class LegacyTLSAdapter(HTTPAdapter):
    """HTTPAdapter that keeps the legacy-renegotiation option on campus pools.

    The context — not the ``verify`` argument — carries the policy: requests
    replaces a custom context whenever ``verify`` is truthy, which would drop
    ``OP_LEGACY_SERVER_CONNECT`` and break the hosts this adapter exists for.
    So the ``verify`` flag is normalised to ``False`` on the way in, and the
    context decides whether certificates are checked.
    """

    insecure: bool
    verify: bool
    ssl_context: ssl.SSLContext

    def __init__(self, *args, **kwargs):
        self.insecure = insecure_mode()
        # ``verify`` as this adapter hands it to requests: True means the CA
        # bundle is loaded and ``conn.cert_reqs`` is CERT_REQUIRED.
        self.verify = not self.insecure
        self.ssl_context = campus_ssl_context(insecure=self.insecure)
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().proxy_manager_for(proxy, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        """Keep this adapter's context on the pool for every request.

        Requests >= 2.32 would otherwise hand the pool a stock context when
        ``verify`` is truthy, silently dropping the legacy option.
        """
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert
        )
        pool_kwargs.pop("ca_certs", None)
        pool_kwargs.pop("ca_cert_dir", None)
        pool_kwargs["ssl_context"] = self.ssl_context
        # urllib3 re-derives verify_mode from ``cert_reqs``, so this has to
        # agree with the context or the two fight (and ``CERT_NONE`` against
        # ``check_hostname=True`` is an outright ValueError).
        pool_kwargs["cert_reqs"] = "CERT_REQUIRED" if self.verify else "CERT_NONE"
        return host_params, pool_kwargs

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        # Requests >= 2.32 path; the context above owns the policy.
        return super().get_connection_with_tls_context(
            request, verify=False, proxies=proxies, cert=cert
        )

    def cert_verify(self, conn, url, verify, cert):
        """Apply this adapter's policy, not the caller's ``verify`` value.

        Requests sets ``conn.cert_reqs = "CERT_NONE"`` whenever it is handed
        a falsy ``verify``, so the policy has to be passed through here rather
        than spoofed as unverified.
        """
        return super().cert_verify(conn, url, verify=self.verify, cert=cert)


__all__ = ["LegacyTLSAdapter", "campus_ssl_context", "insecure_mode"]
