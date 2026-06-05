import numpy as np
import pytest

from planner.broadcast import (
    ControlKind,
    ActionEntry,
    normalize,
    BroadcastPolicy,
    gds_action_spec,
)
from planner.types import Setpoints


def test_normalize_endpoints_and_midpoint():
    assert normalize(20.0, 20.0, 26.0) == pytest.approx(-1.0)
    assert normalize(26.0, 20.0, 26.0) == pytest.approx(1.0)
    assert normalize(23.0, 20.0, 26.0) == pytest.approx(0.0)


def test_normalize_rejects_degenerate_bounds():
    with pytest.raises(ValueError):
        normalize(1.0, 5.0, 5.0)


def test_gds_action_spec_shape():
    spec = gds_action_spec()
    assert len(spec) == 45
    assert sum(1 for e in spec if e.kind is ControlKind.SAT) == 22
    assert sum(1 for e in spec if e.kind is ControlKind.FLOW) == 22
    assert sum(1 for e in spec if e.kind is ControlKind.CHWST) == 1


def test_broadcast_expands_in_declaration_order():
    spec = [
        ActionEntry(ControlKind.SAT, 20.0, 26.0),
        ActionEntry(ControlKind.FLOW, 4.8, 13.8),
        ActionEntry(ControlKind.CHWST, 13.0, 19.0),
    ]
    bp = BroadcastPolicy(spec)
    out = bp.expand(Setpoints(sat_c=23.0, flow_kg_s=9.3, chwst_c=16.0))
    assert out.shape == (3,)
    np.testing.assert_allclose(out, [0.0, 0.0, 0.0], atol=1e-9)


def test_broadcast_full_gds_vector_endpoints():
    bp = BroadcastPolicy(gds_action_spec())
    out = bp.expand(Setpoints(sat_c=20.0, flow_kg_s=13.8, chwst_c=13.0))
    assert out.shape == (45,)
    np.testing.assert_allclose(out[:22], -1.0)
    np.testing.assert_allclose(out[22:44], 1.0)
    assert out[44] == pytest.approx(-1.0)


def test_broadcast_rejects_empty_spec():
    with pytest.raises(ValueError):
        BroadcastPolicy([])


def test_expand_passes_through_out_of_range():
    spec = [ActionEntry(ControlKind.SAT, 20.0, 26.0)]
    bp = BroadcastPolicy(spec)
    out = bp.expand(Setpoints(sat_c=29.0, flow_kg_s=0.0, chwst_c=0.0))
    assert out[0] > 1.0  # pass-through (not clamped); caller pre-clips
