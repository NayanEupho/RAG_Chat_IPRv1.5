from typing import Dict
from fastapi import Request
from urllib.parse import urlparse

def prepare_saml_request(request: Request) -> Dict:
    """
    Convert FastAPI Request into the dict python3-saml expects.
    Caller should add 'post_data' when handling ACS POST.
    """
    url = str(request.url)
    parsed = urlparse(url)
    server_port = str(parsed.port or (443 if parsed.scheme == "https" else 80))

    return {
        "https": "on" if parsed.scheme == "https" else "off",
        "http_host": request.headers.get("host", parsed.netloc),
        "server_port": server_port,
        "script_name": request.scope.get("root_path", "") or "",
        "get_data": dict(request.query_params),
        "post_data": {},  # caller should replace with form data dict on POST
        "query_string": request.scope.get("query_string", b""),
    }
