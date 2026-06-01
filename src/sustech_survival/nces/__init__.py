# -*- coding: utf-8 -*-
"""
NCES Course Eval — https://cas-proxy.cra.moe
Community project (not official SUSTech).

Requires browser-based auth due to bot-detection redirect on the CAS login page.
"""

from .auth import NCESAuthorizer
from .eval import NCESSurvey

__all__ = ["NCESAuthorizer", "NCESSurvey"]