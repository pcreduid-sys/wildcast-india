"""TEST FIXTURES ONLY - fake API responses shaped like the documented GBIF, iNaturalist, eBird and
IUCN payloads. Used to test connectors, parsing, de-duplication and the UI offline.
These records are synthetic and are NEVER written to the shipped application database.
"""
from __future__ import annotations

import re

import numpy as np

from ingestion.http import FetchError

POOL = [  # (scientific, common, class, order, family, iucn)
    ("Panthera tigris", "Tiger", "Mammalia", "Carnivora", "Felidae", "EN"),
    ("Elephas maximus", "Asian elephant", "Mammalia", "Proboscidea", "Elephantidae", "EN"),
    ("Axis axis", "Chital", "Mammalia", "Artiodactyla", "Cervidae", "LC"),
    ("Rusa unicolor", "Sambar", "Mammalia", "Artiodactyla", "Cervidae", "VU"),
    ("Bos gaurus", "Gaur", "Mammalia", "Artiodactyla", "Bovidae", "VU"),
    ("Melursus ursinus", "Sloth bear", "Mammalia", "Carnivora", "Ursidae", "VU"),
    ("Semnopithecus entellus", "Northern plains gray langur", "Mammalia", "Primates", "Cercopithecidae", "LC"),
    ("Pavo cristatus", "Indian peafowl", "Aves", "Galliformes", "Phasianidae", "LC"),
    ("Merops orientalis", "Asian green bee-eater", "Aves", "Coraciiformes", "Meropidae", "LC"),
    ("Dicrurus macrocercus", "Black drongo", "Aves", "Passeriformes", "Dicruridae", "LC"),
    ("Gyps bengalensis", "White-rumped vulture", "Aves", "Accipitriformes", "Accipitridae", "CR"),
    ("Spilornis cheela", "Crested serpent eagle", "Aves", "Accipitriformes", "Accipitridae", "LC"),
    ("Crocodylus palustris", "Mugger crocodile", "Crocodylia", "Crocodylia", "Crocodylidae", "VU"),
    ("Varanus bengalensis", "Bengal monitor", "Squamata", "Squamata", "Varanidae", "LC"),
    ("Calotes versicolor", "Oriental garden lizard", "Squamata", "Squamata", "Agamidae", "LC"),
    ("Duttaphrynus melanostictus", "Asian common toad", "Amphibia", "Anura", "Bufonidae", "LC"),
    ("Hoplobatrachus tigerinus", "Indian bullfrog", "Amphibia", "Anura", "Dicroglossidae", "LC"),
    ("Tor khudree", "Deccan mahseer", "Actinopterygii", "Cypriniformes", "Cyprinidae", "EN"),
    ("Danaus chrysippus", "Plain tiger", "Insecta", "Lepidoptera", "Nymphalidae", "LC"),
    ("Troides minos", "Southern birdwing", "Insecta", "Lepidoptera", "Papilionidae", None),
]
CALLS: list[str] = []


def _points(rng, lat, lon, rad_deg, n):
    r = rad_deg * np.sqrt(rng.random(n)) * 0.9
    t = rng.random(n) * 2 * np.pi
    return lat + r * np.sin(t), lon + r * np.cos(t) / np.cos(np.radians(lat))


class _Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


def fake_get(url, params=None, retries=2, accept=None, headers=None):
    CALLS.append(url)
    params = params or {}
    rng = np.random.default_rng(abs(hash((url, str(sorted(params.items()))))) % 2**32)
    if "api.gbif.org" in url and "vernacularNames" in url:
        key = int(re.findall(r"species/(\d+)/", url)[0])
        return _Resp({"results": [{"vernacularName": POOL[key % len(POOL)][1], "language": "eng"}]})
    if "api.gbif.org" in url:
        nums = [float(x) for x in re.findall(r"-?\d+\.\d+", params["geometry"])]
        lons, lats = nums[0::2], nums[1::2]
        lat, lon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
        rad = (max(lats) - min(lats)) / 2
        n = 120
        la, lo = _points(rng, lat, lon, rad, n)
        res = []
        off = params.get("offset", 0)
        for i in range(n):
            sp = POOL[rng.integers(len(POOL))]
            key = int(lat * 1e6) + off * 1000 + i
            inat = i % 5 == 0
            yr = int(rng.integers(2005, 2027))
            res.append({"key": key, "scientificName": sp[0] + " Linnaeus", "species": sp[0],
                        "speciesKey": POOL.index(sp) + 1000, "kingdom": "Animalia", "phylum": "Chordata",
                        "class": sp[2], "order": sp[3], "family": sp[4], "iucnRedListCategory": sp[5],
                        "decimalLatitude": round(la[i], 5), "decimalLongitude": round(lo[i], 5),
                        "year": yr, "month": int(rng.integers(1, 13)), "day": int(rng.integers(1, 28)),
                        "basisOfRecord": "HUMAN_OBSERVATION",
                        "datasetName": "iNaturalist research-grade observations" if inat else "eBird Observation Dataset",
                        "occurrenceID": f"https://www.inaturalist.org/observations/{key}" if inat else f"URN:{key}",
                        "coordinateUncertaintyInMeters": 30.0})
        res = [r for r in res if not (r["year"] >= 2026 and r["month"] > 10)]
        return _Resp({"count": 2400, "offset": off, "limit": 300, "endOfRecords": off >= 300, "results": res})
    if "api.inaturalist.org" in url:
        lat = (params["swlat"] + params["nelat"]) / 2
        lon = (params["swlng"] + params["nelng"]) / 2
        la, lo = _points(rng, lat, lon, (params["nelat"] - params["swlat"]) / 2, 60)
        res = []
        for i in range(60):
            sp = POOL[rng.integers(len(POOL))]
            oid = int(lat * 1e6) + i  # overlaps some GBIF-mirrored keys to exercise de-duplication
            res.append({"id": oid, "observed_on": f"2025-{int(rng.integers(1, 13)):02d}-{int(rng.integers(1, 28)):02d}",
                        "quality_grade": "research", "uri": f"https://www.inaturalist.org/observations/{oid}",
                        "obscured": sp[5] in ("EN", "CR"), "geoprivacy": None, "positional_accuracy": 20,
                        "geojson": {"type": "Point", "coordinates": [round(lo[i], 5), round(la[i], 5)]},
                        "taxon": {"id": POOL.index(sp) + 5000, "name": sp[0], "rank": "species",
                                  "preferred_common_name": sp[1],
                                  "iconic_taxon_name": {"Squamata": "Reptilia", "Crocodylia": "Reptilia"}.get(sp[2], sp[2])}})
        return _Resp({"total_results": 60, "page": params.get("page", 1), "per_page": 200, "results": res})
    if "api.ebird.org" in url:
        la, lo = _points(rng, params["lat"], params["lng"], params["dist"] / 111 / 2, 15)
        birds = [p for p in POOL if p[2] == "Aves"]
        return _Resp([{"speciesCode": f"sp{j}", "comName": birds[j % len(birds)][1], "sciName": birds[j % len(birds)][0],
                       "obsDt": "2026-11-01 07:30", "howMany": int(rng.integers(1, 9)), "lat": round(la[j], 4),
                       "lng": round(lo[j], 4), "obsValid": True, "obsReviewed": False, "locationPrivate": False,
                       "subId": f"S{1000 + j}"} for j in range(15)])
    if "api.iucnredlist.org" in url:
        return _Resp({"assessments": [{"year_published": "2021", "latest": False, "red_list_category_code": "VU"},
                                      {"year_published": "2023", "latest": True, "red_list_category_code": "EN"}]})
    raise FetchError("unexpected URL in test")


def failing_get(*_a, **_k):
    raise FetchError("ConnectionError: simulated network failure")
