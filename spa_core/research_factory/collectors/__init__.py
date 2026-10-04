"""spa_core/research_factory/collectors/ — ADR-564 (RM-EVIDENCE-01) package E3.

Read-only evidence collectors. Each module exposes ``collect(now, client, ...) ->
list[observation_row]`` (``evidence_contract.OBS_ROW_FIELDS`` shape), append-only: a changed value
for the same key is a ``revises`` row, never an overwrite. No module here imports
``spa_core.research_factory.http_client`` directly by name — ``client`` is injected by the caller
(an object exposing ``get(host, path, params)`` / ``post_info(info_type, payload)``, matching
``evidence_contract.HTTP_ALLOW``) so these modules work against E1's real client once it lands and
against a fake in tests either way.

LLM_FORBIDDEN, stdlib only. No transactions, no keys — ``eth_call``/HTTP GET (and Hyperliquid's one
allow-listed POST /info) only.
"""
# LLM_FORBIDDEN
