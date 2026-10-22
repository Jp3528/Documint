"""Fixed-origin JSON transport with bounded reads, no redirects, retries or response logs."""

import json
from typing import Literal
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import SecretStr

from .contracts import ProviderError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_opener = build_opener(_NoRedirect())


def post_json(
    key: SecretStr,
    resource: Literal["embeddings", "responses"],
    payload: dict[str, object],
) -> object:
    prefix = "EMBEDDING" if resource == "embeddings" else "LLM"
    request = Request(
        "https://api.openai.com/v1/" + resource,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + key.get_secret_value(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _opener.open(request, timeout=30 if resource == "embeddings" else 45) as response:
            content = response.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            raise ProviderError(prefix + "_RESPONSE_LIMIT")
        return json.loads(content)
    except (URLError, OSError, ValueError) as exc:
        raise ProviderError(prefix + "_REQUEST_FAILED") from exc
