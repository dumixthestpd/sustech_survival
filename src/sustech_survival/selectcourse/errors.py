"""
sustech_survival.selectcourse.errors — Exception types raised by the client.

Single file for now; if more error variants appear (network, auth,
rate-limit) they'll live here too.
"""


class EnrollmentError(RuntimeError):
    """Raised when TIS rejects a write-side enrollment action.

    `jg` is TIS's machine-readable result code ('0', '-1', or other
    non-success). `message` is the human-readable TIS message (often
    Chinese, e.g. "操作失败"). `endpoint` and `rwh` are for log correlation.
    """
    def __init__(self, jg: str, message: str, *, endpoint: str, rwh: str):
        self.jg = jg
        self.message = message
        self.endpoint = endpoint
        self.rwh = rwh
        super().__init__(f"[{endpoint}] rwh={rwh} jg={jg}: {message}")