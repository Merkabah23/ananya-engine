"""Schedule reels (or carousels) on Instagram through Buffer's GraphQL API.

Secrets: BUFFER_API_KEY (Buffer -> Settings -> API), BUFFER_CHANNEL_ID
(run `python -m engine buffer-channels` once to find it).
Buffer posts an Instagram carousel as type 'post' with up to 10 image assets, and a reel as type 'reel' with one
video asset (post['video_url']) whose thumbnail is the cover slide.
"""
from __future__ import annotations

import re
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
    """BUFFER_CHANNEL_ID if set, otherwise the Instagram channel whose name matches one of IG_HANDLES."""
    explicit = config.env("BUFFER_CHANNEL_ID", required=False)
    if explicit or config.DRY_RUN:
        return explicit or "dry-run-channel"
    if "id" not in _channel_cache:
        matches = [c for c in list_channels() if c["service"].lower() == "instagram"
                   and c["name"].lstrip("@").lower() in config.IG_HANDLES]
        if len(matches) != 1:
            raise SystemExit(f"Found {len(matches)} Instagram channels named {config.IG_HANDLE} in Buffer; "
                             "connect the account in Buffer or set BUFFER_CHANNEL_ID.")
        _channel_cache["id"] = matches[0]["id"]
    return _channel_cache["id"]


def hashtags(draft: dict) -> list[str]:
    """The brand tag plus up to four topical ones, cleaned, deduplicated and capped at Instagram's limit."""
    out, seen = [], set()
    for t in [config.BRAND_HASHTAG] + list(draft.get("hashtags") or []):
        tag = "#" + re.sub(r"[^0-9A-Za-z_]", "", str(t).lstrip("#"))
        if len(tag) > 1 and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out[:config.MAX_HASHTAGS]


def caption_with_tags(draft: dict) -> str:
    caption = (draft.get("caption") or "").strip()
    return (caption + "\n\n" + " ".join(hashtags(draft))).strip()


def build_input(post: dict, image_urls: list[str]) -> dict:
    due = datetime.fromisoformat(post["due"]).astimezone(timezone.utc)
    alt = post["draft"].get("alt_text") or f"A text post by {config.DISPLAY_NAME}"
    alts = post.get("alt_texts") or []
    return {
        "channelId": channel_id(),
        "text": caption_with_tags(post["draft"]),
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "needsApproval": config.BUFFER_NEEDS_APPROVAL,
        "assets": [_reel_asset(post, image_urls)] if post.get("video_url") else [{"image": {"url": u, "metadata": {"altText": (alts[k] if k < len(alts) and alts[k] else alt)[:1000]}}}
                   for k, u in enumerate(image_urls[:config.BUFFER_MAX_IMAGES])],  # each slide carries its own words
        "metadata": {"instagram": {"type": "reel" if post.get("video_url") else "post", "shouldShareToFeed": True,
                                   "isAiGenerated": config.IS_AI_GENERATED_FLAG}},
    }


def _reel_asset(post: dict, image_urls: list[str]) -> dict:
    """The reel, with its cover slide as the thumbnail: the cover is what shows on the profile grid."""
    video = {"url": post["video_url"]}
    if image_urls:
        video["thumbnailUrl"] = image_urls[0]
    return {"video": video}


def schedule(post: dict) -> str:
    if config.DRY_RUN:
        return "dry-run"
    out = _gql(CREATE, {"input": build_input(post, post["image_urls"])})["createPost"]
    if out["__typename"] != "PostActionSuccess":
        raise RuntimeError(f"Buffer refused the post: {out.get('message')}")
    return out["post"]["id"]
