"""Verified public CCP SDE build-marker contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

LATEST_URL = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"
ARCHIVE_URL_TEMPLATE = (
    "https://developers.eveonline.com/static-data/tranquility/"
    "eve-online-static-data-{build_id}-jsonl.zip"
)
_BUILD_ID_PATTERN = re.compile(r"[0-9]{1,20}")


def is_valid_build_id(value: str) -> bool:
    return _BUILD_ID_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class BuildManifest:
    build_id: str
    release_date: str
    marker_url: str
    archive_url: str

    @classmethod
    def parse_latest_jsonl(cls, payload: bytes) -> BuildManifest:
        try:
            text = payload.decode("utf-8")
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("official latest.jsonl is malformed") from error
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("official latest.jsonl contains a non-object record")
        matches = [record for record in records if record.get("_key") == "sde"]
        if len(matches) != 1:
            raise ValueError("official latest.jsonl must contain exactly one SDE record")
        record = matches[0]
        build_number = record.get("buildNumber")
        release_date = record.get("releaseDate")
        if (
            type(build_number) is not int
            or build_number < 1
            or not isinstance(release_date, str)
            or not release_date.strip()
        ):
            raise ValueError("official SDE build record has invalid build metadata")
        build_id = str(build_number)
        return cls(
            build_id=build_id,
            release_date=release_date,
            marker_url=LATEST_URL,
            archive_url=ARCHIVE_URL_TEMPLATE.format(build_id=build_id),
        )
