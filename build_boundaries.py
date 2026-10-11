#!/usr/bin/env python3
"""
Add to chrissoria/us-places the outline of every place in it, and the maps
Capitol World draws from those outlines.

The outlines are the Census Bureau's cartographic boundary files at 1:500,000
(public domain): one file each for the states, the counties, the places, the
congressional districts and the two houses' legislative districts of the
whole country. Run build_places.py first; only places in its table are
kept, under the same `place_id`.

Written to places/, and published:

  data/boundaries.parquet     one row per place: its outline as well-known
                              binary (the file is GeoParquet), the box round it,
                              and its middle
  maps/states/CA.json         a state as a grid of squares, each square one of
                              its counties
  maps/counties/CA.json.gz    each county of the state as a grid of squares, each
                              square a city, a named community or the land in
                              neither
  maps/congress/CA.json       the state again, on the same grid, each square one
                              of its congressional districts

A map is a made thing: it holds nothing the outlines and the places table do
not. The grids are the same ones the app's own tools used to write
(tools/make_usmap.mjs and tools/make_counties.mjs in capitol-world), so that
the app can read either.

    python build_boundaries.py                  # everything, published
    python build_boundaries.py --states CA TX   # the maps of only some
    --no-maps      the outlines only
    --write-card   publish the dataset card as well
    --no-upload    write the files but do not publish them
"""

import argparse
import gzip
import json
import logging
import math
import re
import struct
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import build_federal_bills as bills
import build_places as base

log = logging.getLogger(__name__)

HF_REPO = base.HF_REPO
OUT_DIR = base.OUT_DIR
YEAR = 2024
SOURCE = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp"
FILES = {"state": f"cb_{YEAR}_us_state_500k", "county": f"cb_{YEAR}_us_county_500k", "place": f"cb_{YEAR}_us_place_500k",
         "congress": f"cb_{YEAR}_us_cd119_500k", "senate": f"cb_{YEAR}_us_sldu_500k", "house": f"cb_{YEAR}_us_sldl_500k"}
# The maps of a state by its districts: the folder each is written to, and the kind of place its shapes are.
# Only Congress's for now. A legislature's are drawn the same way: add "senate": "state senate district" or "house": "state house district".
LAYERS = {"congress": "congressional district"}
# A district is known by the Census Bureau's full code, which says whose lines it is drawn on; its short one is a county's too.
FULL_CODES = ("congress", "senate", "house")

LONG = 150   # squares along a map's longer side
MARGIN = 5   # squares of margin round it
SUB = 4      # samples across a square
LAND = 5     # samples of 16 that make a square land

# The Census Bureau's outlines are in the North American Datum of 1983, as longitude and latitude.
CRS = {
    "$schema": "https://proj.org/schemas/v0.7/projjson.schema.json", "type": "GeographicCRS", "name": "NAD83",
    "datum": {"type": "GeodeticReferenceFrame", "name": "North American Datum 1983",
              "ellipsoid": {"name": "GRS 1980", "semi_major_axis": 6378137, "inverse_flattening": 298.257222101}},
    "coordinate_system": {"subtype": "ellipsoidal", "axis": [
        {"name": "Geodetic longitude", "abbreviation": "Lon", "direction": "east", "unit": "degree"},
        {"name": "Geodetic latitude", "abbreviation": "Lat", "direction": "north", "unit": "degree"}]},
    "id": {"authority": "EPSG", "code": 4269},
}

# Where each state's capitol stands: latitude, longitude. The star on a state's map goes here.
CAPITOLS = {
    "AL": (32.377, -86.3), "AK": (58.302, -134.42), "AZ": (33.448, -112.097), "AR": (34.746, -92.289), "CA": (38.577, -121.494),
    "CO": (39.739, -104.985), "CT": (41.764, -72.682), "DE": (39.158, -75.524), "DC": (38.89, -77.009), "FL": (30.438, -84.281),
    "GA": (33.749, -84.388), "HI": (21.307, -157.858), "ID": (43.617, -116.2), "IL": (39.798, -89.654), "IN": (39.768, -86.163),
    "IA": (41.591, -93.604), "KS": (39.048, -95.678), "KY": (38.187, -84.875), "LA": (30.457, -91.187), "ME": (44.307, -69.782),
    "MD": (38.979, -76.491), "MA": (42.358, -71.064), "MI": (42.734, -84.555), "MN": (44.955, -93.102), "MS": (32.303, -90.182),
    "MO": (38.579, -92.173), "MT": (46.586, -112.018), "NE": (40.808, -96.7), "NV": (39.164, -119.766), "NH": (43.207, -71.538),
    "NJ": (40.22, -74.77), "NM": (35.682, -105.94), "NY": (42.653, -73.757), "NC": (35.78, -78.639), "ND": (46.821, -100.783),
    "OH": (39.961, -82.999), "OK": (35.492, -97.503), "OR": (44.938, -123.03), "PA": (40.264, -76.884), "RI": (41.831, -71.415),
    "SC": (34.0, -81.033), "SD": (44.367, -100.346), "TN": (36.166, -86.784), "TX": (30.275, -97.74), "UT": (40.777, -111.888),
    "VT": (44.262, -72.581), "VA": (37.539, -77.434), "WA": (47.036, -122.905), "WV": (38.336, -81.612), "WI": (43.075, -89.384),
    "WY": (41.14, -104.82),
}
# Where a county's own building stands, where the seat is a city too large for its middle to say: latitude, longitude.
SEAT_POINTS = {"06073": (32.7215, -117.172), "06037": (34.0537, -118.2428)}


# ── Reading a shapefile: the outlines (.shp) and the table beside them (.dbf) ──────────────────────────

def source_zip(kind, folder):
    """One of the Census Bureau's boundary files, fetched once and kept."""
    path = Path(folder) / "boundaries" / f"{FILES[kind]}.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base.fetch(f"{SOURCE}/{FILES[kind]}.zip").content)
    return path


def read_table(data):
    """The rows of a .dbf file, as dictionaries of text."""
    count, header, record = struct.unpack_from("<IHH", data, 4)
    fields, at = [], 32
    while data[at] != 0x0D:
        fields.append((data[at:at + 11].split(b"\0")[0].decode("latin-1"), data[at + 16]))
        at += 32
    rows = []
    for n in range(count):
        at, row = header + n * record + 1, {}
        for name, length in fields:
            row[name] = data[at:at + length].decode("utf-8", errors="replace").strip()
            at += length
        rows.append(row)
    return rows


def read_shapes(data):
    """Each record's rings, as arrays of [longitude, latitude] points. Every record in these files is a polygon or nothing."""
    shapes, at = [], 100
    while at < len(data):
        length = struct.unpack_from(">I", data, at + 4)[0] * 2
        start, rings = at + 8, []
        if struct.unpack_from("<i", data, start)[0] == 5:
            parts, points = struct.unpack_from("<ii", data, start + 36)
            starts = list(struct.unpack_from(f"<{parts}i", data, start + 44)) + [points]
            xy = np.frombuffer(data, dtype="<f8", count=points * 2, offset=start + 44 + parts * 4).reshape(-1, 2)
            rings = [xy[starts[n]:starts[n + 1]] for n in range(parts)]
        shapes.append(rings)
        at = start + length
    return shapes


def read_outlines(kind, folder):
    """The table and the shapes of one boundary file, side by side: [(row, rings)]."""
    with zipfile.ZipFile(source_zip(kind, folder)) as archive:
        rows = read_table(archive.read(f"{FILES[kind]}.dbf"))
        shapes = read_shapes(archive.read(f"{FILES[kind]}.shp"))
    if len(rows) != len(shapes):
        raise ValueError(f"{FILES[kind]}: {len(rows)} rows but {len(shapes)} shapes")
    return list(zip(rows, shapes))


# ── An outline as well-known binary ────────────────────────────────────────────────────────────────

def ring_area(ring):
    """Twice a ring's area, with its sign: positive if the ring runs clockwise, as the outer rings of a shapefile do."""
    x, y = ring[:, 0], ring[:, 1]
    return float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])) * -1


def holds(ring, point):
    """Whether a point is inside a ring."""
    x, y = ring[:, 0], ring[:, 1]
    crosses = ((y[:-1] <= point[1]) & (point[1] < y[1:])) | ((y[1:] <= point[1]) & (point[1] < y[:-1]))
    if not crosses.any():
        return False
    at = x[:-1][crosses] + (point[1] - y[:-1][crosses]) / (y[1:][crosses] - y[:-1][crosses]) * (x[1:][crosses] - x[:-1][crosses])
    return int(np.sum(at > point[0])) % 2 == 1


def polygons_of(rings):
    """A shapefile's rings sorted into polygons: each outer ring with the holes that lie in it."""
    outers = [ring for ring in rings if ring_area(ring) > 0]
    holes = [ring for ring in rings if ring_area(ring) <= 0]
    if not outers:  # nothing runs the usual way round; take every ring as a piece of land
        return [[ring] for ring in rings]
    polygons = [[ring] for ring in outers]
    for hole in holes:
        home = 0 if len(outers) == 1 else next((n for n, outer in enumerate(outers) if holds(outer, hole[0])), 0)
        polygons[home].append(hole)
    return polygons


def wkb(rings):
    """The outline as well-known binary: a polygon if it is one piece, a multipolygon if several."""
    def polygon(parts):
        body = struct.pack("<BII", 1, 3, len(parts))
        for ring in parts:
            body += struct.pack("<I", len(ring)) + np.ascontiguousarray(ring, dtype="<f8").tobytes()
        return body
    polygons = polygons_of(rings)
    if len(polygons) == 1:
        return polygon(polygons[0])
    return struct.pack("<BII", 1, 6, len(polygons)) + b"".join(polygon(parts) for parts in polygons)


def middle_of(rings):
    """The middle of a shape, weighing each ring by its area: a city of several pieces is where most of it is."""
    area = sum_x = sum_y = 0.0
    for ring in rings:
        x, y = ring[:, 0], ring[:, 1]
        cross = x[:-1] * y[1:] - x[1:] * y[:-1]
        area += float(cross.sum())
        sum_x += float(((x[:-1] + x[1:]) * cross).sum())
        sum_y += float(((y[:-1] + y[1:]) * cross).sum())
    return (sum_x / (3 * area), sum_y / (3 * area)) if area else (float(rings[0][0, 0]), float(rings[0][0, 1]))


def boundaries_table(places, outlines):
    """One row per place in the places table that the Census Bureau draws: its outline, the box round it, and its middle."""
    kinds = dict(zip(places["place_id"], places["kind"]))
    rows, seen = [], set()
    for kind in outlines:
        for row, rings in outlines[kind]:
            code = row["GEOIDFQ"] if kind in FULL_CODES else row["GEOID"]
            if code not in kinds or code in seen or not rings:
                continue
            seen.add(code)
            every = np.concatenate(rings)
            middle = middle_of(rings)
            rows.append({"place_id": code, "kind": kinds[code], "geometry": wkb(rings),
                         "west": float(every[:, 0].min()), "south": float(every[:, 1].min()), "east": float(every[:, 0].max()), "north": float(every[:, 1].max()),
                         "middle_longitude": round(middle[0], 6), "middle_latitude": round(middle[1], 6),
                         "pieces": len(polygons_of(rings)), "points": int(len(every))})
    return pd.DataFrame(rows, columns=["place_id", "kind", "geometry", "west", "south", "east", "north", "middle_longitude", "middle_latitude", "pieces", "points"])


def write_boundaries(table, path):
    """Write the outlines as GeoParquet: a Parquet file that says which column is the geometry, and in what."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    data = pa.Table.from_pandas(table, preserve_index=False)
    geo = {"version": "1.0.0", "primary_column": "geometry",
           "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Polygon", "MultiPolygon"], "crs": CRS}}}
    data = data.replace_schema_metadata({**(data.schema.metadata or {}), b"geo": json.dumps(geo).encode()})
    pq.write_table(data, path, compression="zstd")


# ── The projection the maps use: Albers, as d3's geoAlbersUsa draws the country ────────────────────────

def conic(parallels, rotate, center, scale, translate):
    rad = math.pi / 180
    n = (math.sin(parallels[0] * rad) + math.sin(parallels[1] * rad)) / 2
    c = 1 + math.sin(parallels[0] * rad) * (2 * n - math.sin(parallels[0] * rad))

    def raw(lon, lat):
        r = np.sqrt(c - 2 * n * np.sin(lat * rad)) / n
        return r * np.sin(n * lon * rad), math.sqrt(c) / n - r * np.cos(n * lon * rad)

    middle = raw(np.float64(center[0]), np.float64(center[1]))

    def project(points):
        """[longitude, latitude] points as [x, y] on the map, y running down."""
        points = np.asarray(points, dtype="f8").reshape(-1, 2)
        turned = (points[:, 0] + rotate + 180) % 360 - 180  # the far Aleutians are east of the 180th meridian
        x, y = raw(turned, points[:, 1])
        return np.column_stack([translate[0] + scale * (x - middle[0]), translate[1] - scale * (y - middle[1])])

    return project


K = 1300
LOWER48 = conic((29.5, 45.5), 96, (-0.6, 38.7), K, (487.5, 305))
PROJECTIONS = {
    "AK": conic((55, 65), 154, (-2, 58.5), K * 0.35, (487.5 - 0.307 * K, 305 + 0.201 * K)),
    "HI": conic((8, 18), 157, (-3, 19.9), K, (487.5 - 0.205 * K, 305 + 0.212 * K)),
}


def projection(state):
    return PROJECTIONS.get(state, LOWER48)


def drawn_rings(state, rings):
    """
    The pieces of a place that go on a map. Honolulu County takes in the Northwestern Hawaiian Islands, a string of
    islets reaching 1,200 miles past Kauai: drawn to scale they would leave the eight main islands a few squares.
    """
    if state != "HI":
        return rings
    return [ring for ring in rings if ring[:, 0].max() > -161] or rings


# ── From outlines to squares ───────────────────────────────────────────────────────────────────────

def edges_of(rings, project):
    """Every edge of a shape's outline on the map: an array of [x1, y1, x2, y2]."""
    found = []
    for ring in rings:
        points = project(ring)
        found.append(np.column_stack([points[:-1], points[1:]]))
    return np.concatenate(found) if found else np.zeros((0, 4))


class Frame:
    """A grid of squares laid over a part of the map: where it starts, how big a square is, and how many there are."""

    def __init__(self, box, long=LONG, margin=MARGIN):
        min_x, min_y, max_x, max_y = box
        self.cell = max(max_x - min_x, max_y - min_y) / long
        self.w = math.ceil((max_x - min_x) / self.cell) + margin * 2
        self.h = math.ceil((max_y - min_y) / self.cell) + margin * 2
        self.x0, self.y0 = min_x - margin * self.cell, min_y - margin * self.cell

    def square(self, point):
        """A point on the map in squares across and down."""
        return (point[0] - self.x0) / self.cell, (point[1] - self.y0) / self.cell

    def covered(self, edges):
        """Which sample points are inside a shape: a grid of true and false, SUB samples to a square each way."""
        rows, cols = self.h * SUB, self.w * SUB
        inside = np.zeros((rows, cols), dtype=bool)
        if not len(edges):
            return inside
        scale = SUB / self.cell
        x1, y1 = (edges[:, 0] - self.x0) * scale, (edges[:, 1] - self.y0) * scale
        x2, y2 = (edges[:, 2] - self.x0) * scale, (edges[:, 3] - self.y0) * scale
        low, high = np.minimum(y1, y2), np.maximum(y1, y2)
        # An edge crosses the line through the middle of row r when low <= r + 0.5 < high.
        first = np.clip(np.ceil(low - 0.5), 0, rows).astype(np.int64)
        last = np.clip(np.ceil(high - 0.5), 0, rows).astype(np.int64)
        spans = np.maximum(last - first, 0)
        total = int(spans.sum())
        if not total:
            return inside
        edge = np.repeat(np.arange(len(edges)), spans)
        row = np.arange(total) - np.repeat(np.cumsum(spans) - spans, spans) + np.repeat(first, spans)
        at = x1[edge] + (row + 0.5 - y1[edge]) / (y2[edge] - y1[edge]) * (x2[edge] - x1[edge])
        order = np.lexsort((at, row))
        row, at = row[order], at[order]
        # Along each row the crossings pair off: in, out, in, out.
        firsts = np.flatnonzero(np.r_[True, row[1:] != row[:-1]])
        place = np.arange(total) - np.repeat(firsts, np.diff(np.r_[firsts, total]))
        enters = place % 2 == 0
        enters[-1] = False
        enters[:-1] &= row[1:] == row[:-1]
        start = np.flatnonzero(enters)
        begin = np.clip(np.ceil(at[start] - 0.5), 0, cols).astype(np.int64)
        end = np.clip(np.floor(at[start + 1] - 0.5) + 1, 0, cols).astype(np.int64)
        keep = end > begin
        change = np.zeros((rows, cols + 1), dtype=np.int32)
        np.add.at(change, (row[start][keep], begin[keep]), 1)
        np.add.at(change, (row[start][keep], end[keep]), -1)
        return np.cumsum(change, axis=1)[:, :cols] > 0

    def squares(self, owner, inside=None):
        """
        Each square given to whichever owner covers most of its sample points, if enough of it is land at all. `owner` numbers
        each sample point from 1, 0 for none; `inside`, if given, says which points are land.
        """
        blocks = owner.reshape(self.h, SUB, self.w, SUB).transpose(0, 2, 1, 3).reshape(self.h, self.w, SUB * SUB)
        land = (blocks > 0).sum(axis=2) if inside is None else inside.reshape(self.h, SUB, self.w, SUB).transpose(0, 2, 1, 3).reshape(self.h, self.w, -1).sum(axis=2)
        best = np.zeros((self.h, self.w), dtype=np.int32)
        most = np.zeros((self.h, self.w), dtype=np.int32)
        for value in np.unique(owner):
            if value == 0:
                continue
            count = (blocks == value).sum(axis=2)
            wins = count > most
            best[wins], most[wins] = value, count[wins]
        best[land < LAND] = 0
        return best


def runs_of(grid):
    """Runs along the rows of a grid: which shape, then how many squares, and so on."""
    flat = np.asarray(grid).ravel()
    starts = np.flatnonzero(np.r_[True, flat[1:] != flat[:-1]])
    lengths = np.diff(np.r_[starts, len(flat)])
    return [int(value) for pair in zip(flat[starts], lengths) for value in pair]


def box_of(edges):
    return float(edges[:, 0].min()), float(edges[:, 1].min()), float(edges[:, 0].max()), float(edges[:, 1].max())


def nearest_spare(grid, held, at):
    """The square nearest a point that is sea, or that its owner can spare (it has another)."""
    h, w = grid.shape
    cx, cy = min(w - 1, max(0, int(at[0]))), min(h - 1, max(0, int(at[1])))
    for reach in range(max(w, h)):
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                if max(abs(dx), abs(dy)) != reach:
                    continue
                x, y = cx + dx, cy + dy
                if x < 0 or y < 0 or x >= w or y >= h:
                    continue
                owner = int(grid[y, x])
                if owner and held.get(owner, 0) < 2:
                    continue
                return x, y
    return None


def state_frame(state, counties):
    """The grid a state's maps are drawn on: the one that fits its counties, so that every map of the state lines up with the others."""
    project = projection(state)
    return Frame(box_of(np.concatenate([edges_of(rings, project) for _, _, rings in counties])))


def state_map(state, counties, frame=None):
    """
    A state as a grid of squares, each one of its counties: the file Capitol World draws a state from. `counties` is
    [(code, name, rings)], and every county gets at least one square. Given its districts instead, it is the state cut
    into those; `frame` is then the grid of the state's county map, so that the two can be laid one over the other.
    """
    project = projection(state)
    counties = sorted(counties, key=lambda county: county[0])
    shapes = [edges_of(rings, project) for _, _, rings in counties]
    frame = frame or Frame(box_of(np.concatenate(shapes)))
    owner = np.zeros((frame.h * SUB, frame.w * SUB), dtype=np.int32)
    for n, edges in enumerate(shapes):
        owner[frame.covered(edges)] = n + 1
    grid = frame.squares(owner)
    held = {int(value): int(count) for value, count in zip(*np.unique(grid, return_counts=True)) if value}
    for n, (_, _, rings) in enumerate(counties):
        if held.get(n + 1):
            continue
        spot = nearest_spare(grid, held, frame.square(project(np.array([middle_of(rings)]))[0]))
        if spot:
            taken = int(grid[spot[1], spot[0]])
            if taken:
                held[taken] -= 1
            grid[spot[1], spot[0]] = n + 1
            held[n + 1] = 1
    capital = frame.square(project(np.array([CAPITOLS[state][::-1]]))[0]) if state in CAPITOLS else None
    return {"code": state, "w": frame.w, "h": frame.h, "capital": [round(capital[0], 2), round(capital[1], 2)] if capital else None,
            "ids": [code for code, _, _ in counties], "names": [name for _, name, _ in counties], "runs": runs_of(grid)}


def grid_of(file):
    """A map's grid of squares, from its runs."""
    runs = np.asarray(file["runs"]).reshape(-1, 2)
    if int(runs[:, 1].sum()) != file["w"] * file["h"]:
        raise ValueError(f"{file['code']}: the runs do not fill the grid")
    return np.repeat(runs[:, 0], runs[:, 1]).reshape(file["h"], file["w"])


def state_problems(file):
    """What is wrong with a state's map, if anything: a county with no square, or a capital that stands on none."""
    grid = grid_of(file)
    seen = set(int(value) for value in np.unique(grid))
    found = [f"{file['code']}: {name} has no square" for n, name in enumerate(file["names"]) if n + 1 not in seen]
    if file["capital"] and not grid[int(file["capital"][1]), int(file["capital"][0])]:
        found.append(f"{file['code']}: the capital stands on no county")
    return found


def county_map(code, name, rings, places, state, seat=None):
    """
    A county as a grid of squares: each city and named community a shape, and the land in neither one more. `places` is
    [{"id", "name", "kind", "city", "rings"}] for the places that may reach into it; `seat` is the name of the county's seat.
    """
    project = projection(state)
    border = edges_of(rings, project)
    box = box_of(border)
    frame = Frame(box)
    inside = frame.covered(border)

    def within(point):
        col, row = int((point[0] - frame.x0) * SUB / frame.cell), int((point[1] - frame.y0) * SUB / frame.cell)
        return 0 <= col < frame.w * SUB and 0 <= row < frame.h * SUB and bool(inside[row, col])

    near = []
    for place in places:
        edges = edges_of(place["rings"], project)
        reach = box_of(edges)
        if reach[0] <= box[2] and reach[2] >= box[0] and reach[1] <= box[3] and reach[3] >= box[1]:
            near.append({**place, "edges": edges, "middle": project(np.array([middle_of(place["rings"])]))[0]})
    owner = np.zeros(inside.shape, dtype=np.int32)
    for k, place in enumerate(near):
        covered = frame.covered(place["edges"]) & inside
        owner[covered] = k + 1
        place["spot"] = spot_in(covered, frame, place["middle"])
    none = len(near) + 1
    owner[inside & (owner == 0)] = none
    grid = frame.squares(owner, inside)
    # A place too small to win a square is given the one at its middle, if that is in this county.
    held = set(int(value) for value in np.unique(grid))
    for k, place in enumerate(near):
        if k + 1 in held or not within(place["middle"]):
            continue
        x, y = (int(value) for value in frame.square(place["middle"]))
        grid[y, x] = k + 1
        held.add(k + 1)
    # Number the shapes again, leaving out places with no square here; the land in no place comes last.
    kept = sorted(((place, k + 1) for k, place in enumerate(near) if k + 1 in held), key=lambda pair: pair[0]["name"])
    renumber = np.zeros(none + 1, dtype=np.int32)
    for k, (_, old) in enumerate(kept):
        renumber[old] = k + 1
    open_land = bool((grid == none).any())
    if open_land:
        renumber[none] = len(kept) + 1
    grid = renumber[grid]

    seat_place = None
    if seat:
        named = [place for place in near if place["spot"] is not None and seat_names(place["name"]) & seat_names(seat)]
        seat_place = sorted(named, key=lambda place: (plain(place["name"]) != plain(seat), not place["city"]))[0] if named else None
    point = project(np.array([SEAT_POINTS[code][::-1]]))[0] if code in SEAT_POINTS else seat_place["spot"] if seat_place else None
    return {
        "code": code, "name": name, "w": frame.w, "h": frame.h,
        "ids": [place["id"] for place, _ in kept] + ([f"{code}-u"] if open_land else []),
        "names": [place["name"] for place, _ in kept] + (["Unincorporated"] if open_land else []),
        "kinds": [place["kind"] for place, _ in kept] + ([""] if open_land else []),
        "seat": {"name": seat, "place": seat_place["id"] if seat_place and seat_place["city"] else "",
                 "at": [round(float(value), 2) for value in frame.square(point)]} if seat and point is not None else None,
        "runs": runs_of(grid),
    }


def spot_in(covered, frame, middle):
    """
    Where to mark a place on a county's map: its middle, if that is on the part of it in this county, and otherwise the
    point of that part nearest the middle of the part. None if no part of it is in the county. A city on a bay has its
    middle in the water, and a city in two counties may have it in the other.
    """
    if not covered.any():
        return None
    scale = SUB / frame.cell
    col, row = int((middle[0] - frame.x0) * scale), int((middle[1] - frame.y0) * scale)
    if 0 <= row < covered.shape[0] and 0 <= col < covered.shape[1] and covered[row, col]:
        return middle
    rows, cols = np.nonzero(covered)
    nearest = np.argmin((rows - rows.mean()) ** 2 + (cols - cols.mean()) ** 2)
    return frame.x0 + (cols[nearest] + 0.5) / scale, frame.y0 + (rows[nearest] + 0.5) / scale


def plain(name):
    """A name without its accents, its state, or the difference between "Saint" and "St."."""
    name = unicodedata.normalize("NFKD", name.split(",")[0]).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"\bst\.?(?= )", "saint", name)).strip()


def seat_names(name):
    """
    The names a place may go by, so that a seat can be found among a county's places. "San Buenaventura (Ventura)" is
    both; "Macon-Bibb County" is Macon; "Town of Pecos" and "Boise City" are Pecos and Boise; "Urban Honolulu" is Honolulu.
    A name is never shortened from the front otherwise: New Boston is not Boston.
    """
    names = {plain(part) for part in [name, *re.split(r"\s*[()]\s*", name)] if part.strip()}
    for known in list(names):
        names.add(re.split(r"[-/]", known)[0].strip())
        names.add(re.sub(r"^(city|town|village) of |^urban ", "", known))
        names.add(re.sub(r" (city|town|township|court ?house)$", "", known))
    return {known for known in names if known}


# ── Everything ─────────────────────────────────────────────────────────────────────────────────────

def base_state(fips):
    """A state's postal code, from the Census Bureau's number for it."""
    return next((state for state, code in base.FIPS.items() if code == fips), "")


def build_maps(states, places, outlines, out_dir, communities=True):
    """Write the map of each state asked for, and of each of its counties. Returns how many of each were written."""
    known = places.set_index("place_id")
    codes = {**base.FIPS}
    counties_by_state, places_by_state = {}, {}
    for row, rings in outlines["county"]:
        if rings and row["GEOID"] in known.index:
            counties_by_state.setdefault(row["STATEFP"], []).append((row["GEOID"], row["NAME"], drawn_rings(base_state(row["STATEFP"]), rings)))
    for row, rings in outlines["place"]:
        if not rings or row["GEOID"] not in known.index:
            continue
        kind = known.at[row["GEOID"], "kind"]
        if kind == "community" and not communities:
            continue
        places_by_state.setdefault(row["STATEFP"], []).append({
            "id": row["GEOID"], "name": row["NAME"], "city": kind == "city",
            "kind": known.at[row["GEOID"], "government"] if kind == "city" else "community", "rings": rings})
    districts_by_state = {layer: {} for layer in LAYERS}
    for layer in LAYERS:
        for row, rings in outlines.get(layer, []):
            if rings and row["GEOIDFQ"] in known.index:
                state = base_state(row["STATEFP"])
                districts_by_state[layer].setdefault(row["STATEFP"], []).append((row["GEOIDFQ"], known.at[row["GEOIDFQ"], "name"], drawn_rings(state, rings)))
    for folder in ("states", "counties", *LAYERS):
        (out_dir / "maps" / folder).mkdir(parents=True, exist_ok=True)
    written = {"states": 0, "counties": 0, "shapes": 0, "seats": 0, "districts": 0, "problems": 0}
    for state in states:
        fips = codes.get(state)
        counties = counties_by_state.get(fips, [])
        if not counties or state == "DC":  # the District is one county, and has its own way in
            continue
        drawn = state_map(state, counties)
        for problem in state_problems(drawn):
            log.warning(problem)
            written["problems"] += 1
        (out_dir / "maps" / "states" / f"{state}.json").write_text(json.dumps(drawn, separators=(",", ":")), encoding="utf-8")
        written["states"] += 1
        frame = state_frame(state, counties)
        for layer, kind in LAYERS.items():
            districts = districts_by_state[layer].get(fips, [])
            if not districts:  # Nebraska has one house
                continue
            cut = state_map(state, districts, frame)
            for problem in state_problems(cut):
                log.warning(f"{layer} {problem}")
                written["problems"] += 1
            rows = known.loc[cut["ids"]]
            whole = lambda column: [None if pd.isna(value) else int(value) for value in rows[column]]
            cut = {**cut, "kind": kind, "session": rows["district_session"].iloc[0], "short": rows["district"].tolist(),
                   "people": whole("population"), "income": whole("median_household_income"), "home": whole("median_home_value")}
            (out_dir / "maps" / layer / f"{state}.json").write_text(json.dumps(cut, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            written["districts"] += len(cut["ids"])
        boxes = [(place, np.concatenate(place["rings"])) for place in places_by_state.get(fips, [])]
        boxes = [(place, (every[:, 0].min(), every[:, 1].min(), every[:, 0].max(), every[:, 1].max())) for place, every in boxes]
        maps = {}
        for code, name, rings in sorted(counties, key=lambda county: county[0]):
            every = np.concatenate(rings)
            west, south, east, north = every[:, 0].min(), every[:, 1].min(), every[:, 0].max(), every[:, 1].max()
            close = [place for place, box in boxes if box[0] <= east and box[2] >= west and box[1] <= north and box[3] >= south]
            seat = known.at[code, "seat"]
            maps[code] = county_map(code, name, rings, close, state, seat if isinstance(seat, str) and seat else None)
            written["counties"] += 1
            written["shapes"] += len(maps[code]["ids"])
            written["seats"] += maps[code]["seat"] is not None
        with gzip.open(out_dir / "maps" / "counties" / f"{state}.json.gz", "wt", encoding="utf-8") as f:
            json.dump({"schema": 1, "state": state, "counties": maps}, f, ensure_ascii=False, separators=(",", ":"))
        log.info(f"{state}: {len(maps)} counties")
    return written


def upload(out_dir, with_maps, with_card=False):
    from huggingface_hub import CommitOperationAdd, HfApi
    problem = bills.hf_write_problem(HF_REPO)
    if problem:
        log.error(f"Outlines not uploaded: {problem}")
        return False
    operations = [CommitOperationAdd(path_in_repo="data/boundaries.parquet", path_or_fileobj=str(out_dir / "boundaries.parquet"))]
    if with_maps:
        for path in sorted((out_dir / "maps").rglob("*.json*")):
            operations.append(CommitOperationAdd(path_in_repo=str(path.relative_to(out_dir)), path_or_fileobj=str(path)))
    if with_card and base.CARD_FILE.exists():
        operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(base.CARD_FILE)))
    HfApi(token=bills.HF_TOKEN).create_commit(repo_id=HF_REPO, repo_type="dataset", operations=operations,
                                              commit_message=f"Update outlines and maps ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add each place's outline to us-places, and the maps drawn from them")
    parser.add_argument("--states", nargs="+", default=sorted(base.FIPS), help="postal codes of the states to draw maps of")
    parser.add_argument("--out", default=str(OUT_DIR), help="directory holding places.parquet, to write into")
    parser.add_argument("--no-maps", action="store_true", help="write the outlines only")
    parser.add_argument("--no-communities", action="store_true", help="draw cities only on a county's map, as the maps first were")
    parser.add_argument("--no-upload", action="store_true", help="write the files but do not publish them")
    parser.add_argument("--write-card", action="store_true", help="publish the dataset card too")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    if not args.no_upload and not bills.HF_TOKEN:
        parser.error("no Hugging Face token; pass --no-upload to write the files only")
    try:
        places = pd.read_parquet(out_dir / "places.parquet")
        outlines = {kind: read_outlines(kind, OUT_DIR) for kind in FILES}
        table = boundaries_table(places, outlines)
        write_boundaries(table, out_dir / "boundaries.parquet")
        written = {"states": 0, "counties": 0, "shapes": 0, "seats": 0, "districts": 0, "problems": 0} if args.no_maps else build_maps(args.states, places, outlines, out_dir, not args.no_communities)
    except Exception as e:
        log.error(f"Outlines not built: {type(e).__name__}: {e}")
        return 1
    pushed = False if args.no_upload else upload(out_dir, not args.no_maps, args.write_card)
    drawn = table["kind"].value_counts()
    wanted = places[places["kind"] != "nation"]["kind"].value_counts()
    log.info("RESULT: us-places-boundaries " + " ".join(f"{kind}={int(drawn.get(kind, 0))}/{int(count)}" for kind, count in wanted.items())
             + f" megabytes={(out_dir / 'boundaries.parquet').stat().st_size / 1e6:.1f} state_maps={written['states']} county_maps={written['counties']} "
               f"shapes={written['shapes']} seats={written['seats']} districts_drawn={written['districts']} problems={written['problems']} pushed={pushed}")
    return 0 if args.no_upload or pushed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
