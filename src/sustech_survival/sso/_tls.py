"""Session-scoped legacy TLS compatibility, including proxy connections."""

import ssl

from requests.adapters import HTTPAdapter


class LegacyTLSAdapter(HTTPAdapter):
    """Keep the existing CAS/Primo TLS policy on direct and proxied pools."""

    def __init__(self, *args, **kwargs):
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().proxy_manager_for(proxy, **kwargs)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        # Requests >= 2.32 otherwise replaces the custom context for verify=True.
        return super().get_connection_with_tls_context(
            request, verify=False, proxies=proxies, cert=cert
        )

    def cert_verify(self, conn, url, verify, cert):
        # Preserve the same policy on Requests 2.28–2.31 as well.
        return super().cert_verify(conn, url, verify=False, cert=cert)
