"""Shared slowapi Limiter instance.

Import this in routers that need rate limiting:

    from automail.core.rate_limit import limiter

Then attach it to the app in main.py:

    from automail.core.rate_limit import limiter
    app.state.limiter = limiter
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
