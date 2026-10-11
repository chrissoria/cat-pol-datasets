"""build_boundaries turns the Census Bureau's outlines into a table of them, and into the grids of squares the maps are drawn from."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import build_boundaries as maps


def box(west, south, east, north, clockwise=True):
    """A rectangle as a shapefile draws one: closed, and clockwise if it is land."""
    ring = np.array([[west, south], [west, north], [east, north], [east, south], [west, south]], dtype="f8")
    return ring if clockwise else ring[::-1]


def test_a_shape_of_one_piece_is_a_polygon_and_its_hole_goes_with_it():
    blob = maps.wkb([box(0, 0, 10, 10), box(4, 4, 6, 6, clockwise=False)])
    order, kind, rings = struct.unpack_from("<BII", blob)
    assert (order, kind, rings) == (1, 3, 2) and len(blob) == 9 + 2 * (4 + 5 * 16)


def test_a_shape_of_several_pieces_is_a_multipolygon_with_each_hole_in_the_piece_it_lies_in():
    blob = maps.wkb([box(0, 0, 10, 10), box(20, 0, 30, 10), box(24, 4, 26, 6, clockwise=False)])
    assert struct.unpack_from("<BII", blob) == (1, 6, 2)
    assert [len(polygon) for polygon in maps.polygons_of([box(0, 0, 10, 10), box(20, 0, 30, 10), box(24, 4, 26, 6, clockwise=False)])] == [1, 2]


def test_the_middle_of_a_shape_is_where_most_of_it_is():
    x, y = maps.middle_of([box(0, 0, 10, 10), box(100, 0, 101, 1)])
    assert 0.9 < x - 5 < 1.1 and 4.9 < y < 5.1  # the small piece far off pulls it a little, and no more


def test_only_places_in_the_table_get_an_outline_and_each_gets_one():
    places = pd.DataFrame({"place_id": ["06", "06073"], "kind": ["state", "county"]})
    outlines = {"state": [({"GEOID": "06"}, [box(-124, 32, -114, 42)]), ({"GEOID": "72"}, [box(-67, 18, -65, 19)])],
                "county": [({"GEOID": "06073"}, [box(-117.6, 32.5, -116, 33.5)]), ({"GEOID": "06073"}, [box(0, 0, 1, 1)])], "place": []}
    table = maps.boundaries_table(places, outlines)
    assert table["place_id"].tolist() == ["06", "06073"] and table["kind"].tolist() == ["state", "county"]
    county = table.iloc[1]
    assert (county["west"], county["south"], county["east"], county["north"]) == (-117.6, 32.5, -116, 33.5) and county["pieces"] == 1


def test_a_grid_is_written_as_runs_along_its_rows():
    assert maps.runs_of(np.array([[0, 0, 1], [1, 2, 2]])) == [0, 2, 1, 2, 2, 2]


def flat(points):
    """A projection that leaves longitude and latitude as they are, north up."""
    points = np.asarray(points, dtype="f8").reshape(-1, 2)
    return np.column_stack([points[:, 0], -points[:, 1]])


grid_of = maps.grid_of


def test_the_sample_points_inside_a_shape_are_found_and_a_hole_is_left_out():
    frame = maps.Frame((0, 0, 10, 10), long=10, margin=0)
    covered = frame.covered(maps.edges_of([box(0, -10, 10, 0), box(4, -6, 6, -4, clockwise=False)], flat))
    assert covered.shape == (40, 40) and covered.sum() == 40 * 40 - 8 * 8 and not covered[20, 20] and covered[2, 2]


def test_a_state_is_cut_into_its_counties_and_a_county_too_small_for_a_square_is_still_given_one(monkeypatch):
    monkeypatch.setattr(maps, "projection", lambda state: flat)
    counties = [("99003", "East", [box(5, 0, 10, 10)]), ("99001", "West", [box(0, 0, 5, 10)]), ("99005", "Speck", [box(2, 5, 2.001, 5.001)])]
    file = maps.state_map("ZZ", counties)
    grid = grid_of(file)
    assert file["ids"] == ["99001", "99003", "99005"] and file["names"] == ["West", "East", "Speck"] and (file["w"], file["h"]) == (160, 160)
    assert (grid == 3).sum() == 1 and abs(int((grid == 1).sum()) - 150 * 75) <= 1 and (grid == 2).sum() == 150 * 75
    assert grid[80, 20] == 1 and grid[80, 140] == 2 and grid[0, 0] == 0


def test_a_county_is_cut_into_its_cities_its_communities_and_the_land_in_neither(monkeypatch):
    monkeypatch.setattr(maps, "projection", lambda state: flat)
    places = [
        {"id": "9900100", "name": "Seatville", "kind": "city", "city": True, "rings": [box(1, 1, 4, 4)]},
        {"id": "9900200", "name": "Hollow", "kind": "community", "city": False, "rings": [box(6, 6, 8, 8)]},
        {"id": "9900300", "name": "Elsewhere", "kind": "city", "city": True, "rings": [box(20, 20, 22, 22)]},  # near, and not in the county
        {"id": "9900400", "name": "Astride", "kind": "town", "city": True, "rings": [box(9, 4, 11, 6)]},  # half of it is over the line
    ]
    file = maps.county_map("99001", "Test", [box(0, 0, 10, 10)], places, "ZZ", seat="Seatville")
    grid = grid_of(file)
    assert file["ids"] == ["9900400", "9900200", "9900100", "99001-u"] and file["names"] == ["Astride", "Hollow", "Seatville", "Unincorporated"]
    assert file["kinds"] == ["town", "community", "city", ""]
    assert (grid == 3).sum() == 45 * 45 and (grid == 2).sum() == 30 * 30 and (grid == 1).sum() == 15 * 30
    assert (grid > 0).sum() == 150 * 150
    seat = file["seat"]
    assert seat["name"] == "Seatville" and seat["place"] == "9900100" and abs(seat["at"][0] - (5 + 2.5 * 15)) < 0.01 and abs(seat["at"][1] - (5 + 7.5 * 15)) < 0.01


def test_a_seat_that_is_a_community_is_marked_and_names_no_city(monkeypatch):
    monkeypatch.setattr(maps, "projection", lambda state: flat)
    places = [{"id": "9900200", "name": "Hollow", "kind": "community", "city": False, "rings": [box(6, 6, 8, 8)]}]
    assert maps.county_map("99001", "Test", [box(0, 0, 10, 10)], places, "ZZ", seat="Hollow")["seat"]["place"] == ""
    assert maps.county_map("99001", "Test", [box(0, 0, 10, 10)], places, "ZZ", seat="Nowhere")["seat"] is None
    assert maps.county_map("99001", "Test", [box(0, 0, 10, 10)], places, "ZZ")["seat"] is None


def test_a_seat_is_found_under_the_names_its_place_goes_by_and_never_under_a_neighbours():
    same = lambda place, seat: bool(maps.seat_names(place) & maps.seat_names(seat))
    assert same("San Buenaventura (Ventura)", "Ventura") and same("Macon-Bibb County", "Macon") and same("Boise City", "Boise")
    assert same("Town of Pecos", "Pecos") and same("Urban Honolulu", "Honolulu") and same("St. Paul", "Saint Paul")
    assert same("Utqiaġvik", "Utqiagvik") and same("Benton", "Benton, Illinois") and same("Heber", "Heber City")
    assert not same("New Boston", "Boston") and not same("Fairfax Station", "Fairfax") and not same("East Lexington", "Lexington")


def test_a_place_whose_middle_is_in_the_water_is_marked_on_its_own_land():
    frame = maps.Frame((0, 0, 10, 10), long=10, margin=0)
    covered = np.zeros((40, 40), dtype=bool)
    covered[0:4, 0:4] = True
    assert maps.spot_in(covered, frame, (0.5, 0.5)) == (0.5, 0.5)
    x, y = maps.spot_in(covered, frame, (9, 9))
    assert 0 < x < 1 and 0 < y < 1
    assert maps.spot_in(np.zeros((40, 40), dtype=bool), frame, (5, 5)) is None


def test_the_far_aleutians_are_drawn_beside_the_rest_of_alaska():
    east, west = maps.PROJECTIONS["AK"]([[179.5, 52.0]])[0], maps.PROJECTIONS["AK"]([[-179.5, 52.0]])[0]
    assert abs(east[0] - west[0]) < 10 and east[0] < west[0]


def test_a_state_map_with_a_county_left_out_or_a_capital_at_sea_is_reported(monkeypatch):
    monkeypatch.setattr(maps, "projection", lambda state: flat)
    file = maps.state_map("ZZ", [("99001", "West", [box(0, 0, 5, 10)]), ("99003", "East", [box(5, 0, 10, 10)])])
    assert maps.state_problems({**file, "capital": [80, 80]}) == []
    assert maps.state_problems({**file, "capital": [1, 1]}) == ["ZZ: the capital stands on no county"]
    assert maps.state_problems({**file, "names": ["West", "East", "Lost"], "capital": None}) == ["ZZ: Lost has no square"]


def test_hawaiis_far_islets_are_left_off_its_maps_and_nothing_is_left_off_anyone_elses():
    oahu, islet = box(-158.3, 21.2, -157.6, 21.7), box(-171.8, 25.7, -171.7, 25.8)
    assert len(maps.drawn_rings("HI", [oahu, islet])) == 1 and len(maps.drawn_rings("CA", [oahu, islet])) == 2
    assert len(maps.drawn_rings("HI", [islet])) == 1  # a place that is only far islets is still drawn


def test_a_district_is_matched_by_its_full_code_and_never_taken_for_the_county_with_the_same_short_one():
    places = pd.DataFrame({"place_id": ["06039", "610U900US06039"], "kind": ["county", "state senate district"]})
    outlines = {"county": [({"GEOID": "06039"}, [box(-120, 37, -119, 38)])],
                "senate": [({"GEOID": "06039", "GEOIDFQ": "610U900US06039"}, [box(-117.5, 32.5, -117, 33)])]}
    table = maps.boundaries_table(places, outlines).set_index("place_id")
    assert table.loc["06039", "west"] == -120 and table.loc["610U900US06039", "west"] == -117.5 and len(table) == 2


def test_a_states_districts_are_drawn_on_the_grid_of_its_counties_so_the_two_line_up(monkeypatch):
    monkeypatch.setattr(maps, "projection", lambda state: flat)
    counties = [("99001", "West", [box(0, 0, 5, 10)]), ("99003", "East", [box(5, 0, 10, 10)])]
    districts = [("5001900US9902", "South", [box(0.1, 0.1, 9.9, 5)]), ("5001900US9901", "North", [box(0.1, 5, 9.9, 9.9)])]  # a hair inside the state
    frame = maps.state_frame("ZZ", counties)
    by_county, by_district = maps.state_map("ZZ", counties), maps.state_map("ZZ", districts, frame)
    assert (by_district["w"], by_district["h"]) == (by_county["w"], by_county["h"]) and by_district["ids"] == ["5001900US9901", "5001900US9902"]
    counties_grid, districts_grid = grid_of(by_county), grid_of(by_district)
    assert districts_grid[20, 80] == 1 and districts_grid[140, 80] == 2  # north is up
    assert ((districts_grid > 0) & (counties_grid == 0)).sum() == 0 and maps.state_problems(by_district) == []
