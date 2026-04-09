"""
HTTP session factory with proxy support and common headers.
"""

import requests
from .proxy import ProxyManager


def create_session(
    user_agent: str = "",
    proxy_manager: ProxyManager | None = None,
    use_proxy: bool = False,
) -> requests.Session:
    """Create a requests.Session with sensible defaults."""
    session = requests.Session()
    if user_agent:
        session.headers["User-Agent"] = user_agent
    session.headers["Accept-Language"] = "en-US,en;q=0.9"
    session.headers["Accept-Encoding"] = "gzip, deflate, br"

    if use_proxy and proxy_manager:
        proxy_dict = proxy_manager.get_next()
        if proxy_dict:
            session.proxies.update(proxy_dict)

    return session
