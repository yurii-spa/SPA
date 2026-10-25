# Probe context — STUDIO-OS-MODELS-01 status (fixed text, 2026-10-25)

- Branch: integ/studio-os-next-01-stab.
- Verified code revision: 393faa72d112007eb1031b63fc43313fb377cd80 (ARB-accepted on 2026-10-24).
- Full CI run 40131303808 on that revision: RED, 12 of 12 shards complete, 2 failed tests.
- Both failing tests check the producer tick of criterion §49; the §49 producer is not installed.
- Production routing of models is NOT enabled: every role assignment in architecture/model_roles.json is null.
- A second real model provider is NOT connected.
- Census run 40131301479 on 393faa72d: 22 findings, 78 unmeasured.
- The documentation-only HEAD on top of the verified revision is 79fa6e21d; no CI or census was run on it.
