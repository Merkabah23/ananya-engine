"""Schedule carousels on Instagram through Buffer's GraphQL API.

Secrets: BUFFER_API_KEY (Buffer -> Settings -> API), BUFFER_CHANNEL_ID
(run `python -m engine buffer-channels` once to find it).
Buffer posts an Instagram carousel as type 'post' with up to 10 image assets.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from . import config

CREATE = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id dueAt status } }
    ... on MutationError { message }
  }
}"""

ORGS = "query { account { organizations { id name } } }"
CHANNELS = """query Channels($input: ChannelsInput!) { channels(input: $input) { id name service } }"""


def _gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(config.BUFFER_API, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {config.env('BUFFER_API_KEY')}"}, timeout=60)
    if r.status_code == 429:
        raise RuntimeError("Buffer rate limit reached; try again later.")
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {body['errors']}")
    return body["data"]


def list_channels() -> list[dict]:
    out = []
    for org in _gql(ORGS)["account"]["organizations"]:
        for ch in _gql(CHANNELS, {"input": {"organizationId": org["id"]}})["channels"]:
            out.append({"organization": org["name"], **ch})
    return out


_channel_cache: dict = {}


def channel_id() -> str:
    """BUFFER_CHANNEL_ID if set, otherwise the Instagram channel whose name matches IG_HANDLE."""
    explicit = config.env("BUFFER_CHANNEL_ID", required=False)
    if explicit or config.DRY_RUN:
        return explicit or "dry-run-channel"
    if "id" not in _channel_cache:
        matches = [c for c in list_channels() if c["service"].lower() == "instagram"
                   and c["name"].lstrip("@").lower() == config.IG_HANDLE.lower()]
        if len(matches) != 1:
            raise SystemExit(f"Found {len(matches)} Instagram channels named {config.IG_HANDLE} in Buffer; "
                             "connect the account in Buffer or set BUFFER_CHANNEL_ID.")
        _channel_cache["id"] = matches[0]["id"]
    return _channel_cache["id"]


def build_input(post: dict, image_urls: list[str]) -> dict:
    due = datetime.fromisoformat(post["due"]).astimezone(timezone.utc)
    alt = post["draft"].get("alt_text") or f"A text post by {config.DISPLAY_NAME}"
    return {
        "channelId": channel_id(),
        "text": post["draft"].get("caption", ""),
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "needsApproval": False,
        "assets": [{"image": {"url": u, "metadata": {"altText": alt[:1000]}}} for u in image_urls[:config.BUFFER_MAX_IMAGES]],
        "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True,
                                   "isAiGenerated": config.IS_AI_GENERATED_FLAG}},
    }


def schedule(post: dict) -> str:
    if config.DRY_RUN:
        return "dry-run"
    out = _gql(CREATE, {"input": build_input(post, post["image_urls"])})["createPost"]
    if out["__typename"] != "PostActionSuccess":
        raise RuntimeError(f"Buffer refused the post: {out.get('message')}")
    return out["post"]["id"]
