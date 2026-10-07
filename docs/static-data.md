# Static fitting catalog

Fitting discovery and validation require a local versioned static catalog.
MCP startup never downloads data. `eve-mcp static-data status` is offline;
`clear` touches only static-data cache/catalog paths. Refresh and deletion are
operator-invoked CLI operations.

```text
eve-mcp static-data status
eve-mcp static-data refresh
eve-mcp static-data refresh --force
eve-mcp static-data clear --build <build-id> --yes
eve-mcp static-data clear --all --yes
```

The default imported catalog location is
`~/.local/share/eve-mcp/static-data/<build-id>/`; the default replaceable raw
cache is `~/.cache/eve-mcp/sde/<build-id>/`. With `EVE_MCP_DATA_DIR` set, both
are isolated under that configured test/operator data directory. The catalog
contains only fitting-relevant static facts. `manifest.json` records the CCP
build/release metadata, archive URL/name, downloaded byte count, SHA-256 of the
actual ZIP bytes, import time, imported type count, and catalog schema version.
The replaceable raw cache retains the downloaded archive. No profile, token,
proposal, or Git-tracked file is written by refresh.

## Official source and importer

The importer uses only CCP's Tranquility SDE endpoints:

```text
https://developers.eveonline.com/static-data/tranquility/latest.jsonl
https://developers.eveonline.com/static-data/tranquility/eve-online-static-data-<build>-jsonl.zip
```

The JSONL marker is parsed for exactly one record with `_key: "sde"` and
integer `buildNumber`. The archive is checked against its internal
`_sde.jsonl` build number before import. For the official build observed on
2026-10-07, the marker reported build `3586130`, release date
`2026-10-07T11:10:05Z`; the archive was 99,297,801 bytes with SHA-256
`b6efc200ec30911e5d22decc8ee3c34cafeac1ecc49faa76491fd75fa6c36045`.
Refresh computes and records the checksum for every downloaded archive rather
than trusting an HTTP ETag or a third-party checksum.

The importer reads the root-level JSONL datasets `types.jsonl`,
`typeDogma.jsonl`, `dogmaAttributes.jsonl`, `dogmaEffects.jsonl`, `groups.jsonl`,
`categories.jsonl`, and `_sde.jsonl`. It imports published English-named ships,
modules with a known slot effect, charges, and drones, along with hull slot and
fitting-resource attributes, module CPU/power/calibration, and required skill
facts. Other SDE datasets in the ZIP are not imported into the catalog. This
was verified against the official build archive; the narrow import yielded
5,575 fitting-relevant type records. A type without the required Dogma record
or a recognized module slot effect is omitted rather than assigned fabricated
facts. A zero required-skill level in the source record is treated as no
requirement.

The build number pins the source data; it does not make SDE facts a guarantee
of live game behavior. Validation is limited to the imported static fitting
facts and selected character skill response. Unsupported constraints remain
incomplete instead of being guessed. CCP's current SDE terms apply; this
project does not bundle or redistribute an SDE archive. Review the terms at
CCP's official developer site before redistributing cached data.

`status` is offline and never checks for a newer build. `refresh` is the only
network operation: it checks the current marker, skips an already active build,
then downloads and stages the named official archive. `--force` re-downloads
the same build. Redirects are not followed. Invalid markers, missing datasets,
malformed JSONL, an archive/build mismatch, or an import/integrity failure
leave the previous active catalog and cache unchanged. Staging is atomic and
serialized by a local lock. No MCP startup, fitting draft, validation, or
create call refreshes data automatically.

`clear --all --yes` prints the exact static-data paths and total bytes before
removal. It never removes the profile database, keyring values, ESI cache, or
any Git-tracked repository files. Clearing the active build requires `--yes`;
the result warns that fitting drafting/saving is unavailable until refresh.
