"""camera_reader 的离线解析测试与实时快照回归基线。"""
from __future__ import annotations

import struct

import pytest

from san11agent.camera_reader import (
    CameraReadError,
    SHARED_SIZE,
    parse_camera_shared,
)
from san11agent.map_camera import project_map_point

VIEW = (
    0.7071069478988647, -0.4999995529651642, -0.49999988079071045, 0.0,
    0.0, 0.7071067690849304, -0.7071065902709961, 0.0,
    -0.707106351852417, -0.4999999701976776, -0.5000002980232239, 0.0,
    -719.1173095703125, 2573.047607421875, 3195.6767578125, 1.0,
)
PROJECTION = (
    0.0020992786157876253, 0.0, 0.0, 0.0,
    0.0, 0.003732050769031048, 0.0, 0.0,
    0.0, 0.0, 0.0010162601247429848, 0.0010000000474974513,
    0.0, 0.0, -0.016260161995887756, 0.0,
)


def _payload(version=4302, view_seq=2151, proj_seq=2151) -> bytes:
    return struct.pack("<iII16f16f", version, view_seq, proj_seq, *VIEW, *PROJECTION)


def test_parse_camera_shared_roundtrip():
    snapshot = parse_camera_shared(_payload())
    assert snapshot.version == 4302
    assert snapshot.view_sequence == 2151
    assert snapshot.projection_sequence == 2151
    assert snapshot.view[0][0] == pytest.approx(0.7071069478988647)
    assert snapshot.view[3][0] == pytest.approx(-719.1173095703125)
    assert snapshot.projection[0][0] == pytest.approx(0.0020992786157876253)


def test_snapshot_projects_4k_city_point():
    snapshot = parse_camera_shared(_payload())
    camera = snapshot.as_camera(3840, 2160)
    x, y = project_map_point(129, 54, camera)  # 平原
    assert x == pytest.approx(3627.75, abs=20)
    assert y == pytest.approx(183.2, abs=20)


def test_short_payload_raises():
    with pytest.raises(CameraReadError, match="too short"):
        parse_camera_shared(b"\0" * (SHARED_SIZE - 1))


def test_zero_matrix_raises():
    data = struct.pack("<iII16f16f", 1, 0, 0, *([0.0] * 32))
    with pytest.raises(CameraReadError, match="view matrix is all zero"):
        parse_camera_shared(data)
