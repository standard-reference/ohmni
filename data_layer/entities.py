"""The entity and instrument spine, for real names.

CIK is the anchor: it survives renames and delisting, which is exactly why the
ticker is exposed only as a point-in-time attribute and never used as an identity.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    id: str
    cik: str
    name: str
    ticker: str            # point-in-time attribute, never the identity
    wiki: str
    peer_group: str
    gdelt_query: str
    hn_query: str
    #: Exact organization names as GDELT's GKG writes them. A declared alias set,
    #: not a pattern: the same file contains "applebee", "appleton school" and
    #: "taiwanese apple inc", so substring matching on "apple" would build a
    #: series measuring nothing about the entity. Versioned like a concept map.
    gkg_orgs: frozenset[str]

    @property
    def instrument(self) -> str:
        return f"inst_{self.ticker}_common"


ENTITIES: tuple[Entity, ...] = (
    Entity("ent_0001045810", "0001045810", "NVIDIA Corporation", "NVDA",
           "Nvidia", "semiconductors", '"Nvidia"', "Nvidia",
           frozenset({"nvidia", "nvidia corp", "nvidia corporation"})),
    Entity("ent_0000002488", "0000002488", "Advanced Micro Devices, Inc.", "AMD",
           "Advanced_Micro_Devices", "semiconductors", '"Advanced Micro Devices"', "AMD",
           frozenset({"advanced micro devices", "amd"})),
    Entity("ent_0000050863", "0000050863", "Intel Corporation", "INTC",
           "Intel", "semiconductors", '"Intel Corporation"', "Intel",
           frozenset({"intel", "intel corp", "intel corporation"})),
    Entity("ent_0000320193", "0000320193", "Apple Inc.", "AAPL",
           "Apple_Inc.", "technology_hardware", '"Apple Inc"', "Apple",
           frozenset({"apple inc", "apple computer", "apple corp"})),
    Entity("ent_0000789019", "0000789019", "Microsoft Corporation", "MSFT",
           "Microsoft", "software", '"Microsoft Corp"', "Microsoft",
           frozenset({"microsoft", "microsoft corp", "microsoft corporation"})),
    Entity("ent_0001318605", "0001318605", "Tesla, Inc.", "TSLA",
           "Tesla,_Inc.", "automotive", '"Tesla Inc"', "Tesla",
           frozenset({"tesla inc", "tesla motors", "tesla corp"})),
)

BY_ID = {e.id: e for e in ENTITIES}
BY_TICKER = {e.ticker: e for e in ENTITIES}
INSTRUMENT_OF = {e.instrument: e.id for e in ENTITIES}
INSTRUMENTS_OF = {e.id: (e.instrument,) for e in ENTITIES}
PEER_GROUP = {e.id: e.peer_group for e in ENTITIES}


#: Bumped whenever any entity's alias set changes — a different alias set is a
#: different measurement, and a cache filtered with the old one is stale.
GKG_ALIAS_VERSION = "gkg_alias.1"


def gkg_alias_index() -> dict[str, str]:
    """org name -> entity id. Exact keys only."""
    return {org: e.id for e in ENTITIES for org in e.gkg_orgs}
