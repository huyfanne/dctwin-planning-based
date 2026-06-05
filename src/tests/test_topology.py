from webapp.topology import build_hall_topology


def test_topology_has_22_crahs_and_racks_and_plant(tmp_path):
    topo = build_hall_topology(
        building_json="models/building.json",
        dt_prototxt="configs/dt/dt.prototxt",
        hall="1f 2a",
    )
    assert topo["hall"]["name"].lower().endswith("1f 2a")
    assert len(topo["crahs"]) == 22                      # the 22 controlled ACUs
    assert all("pos" in c and len(c["pos"]) == 3 for c in topo["crahs"])
    assert len(topo["rack_rows"]) >= 2
    assert {r["aisle"] for r in topo["rack_rows"]} <= {"cold", "hot"}
    assert topo["plant"]["chiller"] >= 1
    # deterministic layout: same call -> identical positions
    topo2 = build_hall_topology("models/building.json", "configs/dt/dt.prototxt", "1f 2a")
    assert [c["pos"] for c in topo["crahs"]] == [c["pos"] for c in topo2["crahs"]]


def test_building_has_all_stacked_halls():
    topo = build_hall_topology("models/building.json", "configs/dt/dt.prototxt", "1f 2a")
    b = topo["building"]
    assert len(b["footprint"]) == 2 and b["height"] > 0
    halls = b["halls"]
    # the GDS model is 7 data halls / rooms stacked vertically
    assert len(halls) == 7
    # exactly one controlled hall (1F 2A) with the 22 ITE rows
    controlled = [h for h in halls if h["controlled"]]
    assert len(controlled) == 1
    assert controlled[0]["code"].lower().endswith("1f 2a")
    assert controlled[0]["ite"] == 22
    # sorted ground -> top and genuinely stacked (strictly increasing z0)
    z0s = [h["z0"] for h in halls]
    assert z0s == sorted(z0s)
    assert all(b2 > a for a, b2 in zip(z0s, z0s[1:]))
    # every hall carries real geometry + a level label
    for h in halls:
        assert len(h["size"]) == 3 and all(v > 0 for v in h["size"])
        assert h["level"] in {"GF", "1F", "2F", "—"}


def test_parse_zone_bboxes_world_coords():
    from webapp.topology import parse_zone_bboxes
    boxes = parse_zone_bboxes("models/idf/building.idf")
    halls = {z: bb for z, bb in boxes.items() if "hall" in z or "core" in z}
    assert len(halls) == 7
    # each box is non-degenerate
    for bb in halls.values():
        minx, maxx, miny, maxy, minz, maxz = bb
        assert maxx > minx and maxy > miny and maxz > minz
