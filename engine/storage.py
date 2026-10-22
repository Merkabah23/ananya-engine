"""Host rendered slides at stable public URLs (Buffer fetches them at publish time).

Slides go to a separate PUBLIC GitHub repo (e.g. <you>/ananya-media) through GitHub's
contents API and are served from raw.githubusercontent.com, which returns image/jpeg.
The engine repo itself stays private. Secrets:
  MEDIA_REPO        "<owner>/<repo>", e.g. "your-github-user/ananya-media"
  MEDIA_REPO_TOKEN  fine-grained token with Contents: read & write on that repo only
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import requests

from . import config


def upload(local: Path, key: str) -> str:
    if config.DRY_RUN:
        return f"file://{local}"
    repo = config.env("MEDIA_REPO")
    h = {"Authorization": f"Bearer {config.env('MEDIA_REPO_TOKEN')}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}/contents/slides/{key}"
    existing = requests.get(api, headers=h, timeout=30)
    body = {"message": f"slide {key}", "content": base64.b64encode(local.read_bytes()).decode(), "branch": "main"}
    if existing.status_code == 200:
        body["sha"] = existing.json()["sha"]  # re-render of the same slide: overwrite
    r = requests.put(api, headers=h, json=body, timeout=60)
    r.raise_for_status()
    url = f"https://raw.githubusercontent.com/{repo}/main/slides/{key}"
    for _ in range(6):  # new files can take a few seconds to appear on raw.githubusercontent.com
        head = requests.head(url, timeout=30)
        if head.status_code == 200 and head.headers.get("content-type", "").startswith("image/"):
            return url
        time.sleep(5)
    raise RuntimeError(f"Slide not publicly readable as an image ({head.status_code}); is {repo} public?")
