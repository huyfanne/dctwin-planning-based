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
