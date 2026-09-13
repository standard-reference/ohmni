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

    @property
    def instrument(self) -> str:
        return f"inst_{self.ticker}_common"


ENTITIES: tuple[Entity, ...] = (
    Entity("ent_0001045810", "0001045810", "NVIDIA Corporation", "NVDA",
           "Nvidia", "semiconductors", '"Nvidia"', "Nvidia"),
    Entity("ent_0000002488", "0000002488", "Advanced Micro Devices, Inc.", "AMD",
           "Advanced_Micro_Devices", "semiconductors", '"Advanced Micro Devices"', "AMD"),
    Entity("ent_0000050863", "0000050863", "Intel Corporation", "INTC",
           "Intel", "semiconductors", '"Intel Corporation"', "Intel"),
    Entity("ent_0000320193", "0000320193", "Apple Inc.", "AAPL",
           "Apple_Inc.", "technology_hardware", '"Apple Inc"', "Apple"),
    Entity("ent_0000789019", "0000789019", "Microsoft Corporation", "MSFT",
           "Microsoft", "software", '"Microsoft Corp"', "Microsoft"),
    Entity("ent_0001318605", "0001318605", "Tesla, Inc.", "TSLA",
           "Tesla,_Inc.", "automotive", '"Tesla Inc"', "Tesla"),
)

BY_ID = {e.id: e for e in ENTITIES}
BY_TICKER = {e.ticker: e for e in ENTITIES}
INSTRUMENT_OF = {e.instrument: e.id for e in ENTITIES}
INSTRUMENTS_OF = {e.id: (e.instrument,) for e in ENTITIES}
PEER_GROUP = {e.id: e.peer_group for e in ENTITIES}
