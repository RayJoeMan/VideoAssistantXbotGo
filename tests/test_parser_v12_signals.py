"""Tests for the V1.2.0 signal assignment + gap/start-UTC capture.

Regression coverage for the 2026-10-23 calibration findings:
  - center_speed must come from Deque object velocities, not FIN's V
    (which is the camera's pan velocity)
  - center_x falls back to FIN's x (the dense position signal)
  - the parser records the wall-clock start and recording gaps so
    video_sync can map track time to video time
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from telemetry.parser import parse_track_file

HEADER = """\
SDKV1.2.0-RGJK-Type15
Sensor: FALCON-AI-FC1
Lacrosse yawLim45.0 areaTH500 pitchInit5.0
Gear:TELE Drive:5Hz

"""


def _write(tmp_path, body: str) -> Path:
    p = tmp_path / "game.track"
    p.write_text(HEADER + body)
    return p


def test_object_speed_not_camera_pan_speed(tmp_path):
    """Deque rides the FFilter line; FIN V is a fast camera pan."""
    body = (
        "UTC2026-06-20 14:00:00.000\n"
        "Frame1 SZ1 Yaw0 Pit0 fps30\n"
        "FFilterP5 mot3 Deque3(V100,x10)(V40,x20)(V10,x30)\n"
        "Fast2 Crowdx1280\n"
        "FIN:x1280.0 V95.0\n"
        "Zoom:CPSz1 Count0\n"
    )
    result = parse_track_file(_write(tmp_path, body))
    pt = result.points[0]
    # Fastest object 100 * 0.25 = 25 — not the camera's 95
    assert pt.center_speed == 25.0
    assert pt.activity_score == 0.25
    # FIN x 1280 on the 2560 pano -> 500 on the 0-1000 field scale
    assert pt.center_x == 500.0
    assert pt.raw_fields["fin_v"] == "95.0"


def test_start_utc_and_gap_detection(tmp_path):
    body = (
        "UTC2026-06-20 14:00:00.000\n"
        "Frame1 SZ1 Yaw0 Pit0 fps30\n"
        "Deque3(V0.0,x0.0)(V0.0,x0.0)(V0.0,x0.0)\n"
        "Fast0\n"
        "FIN:x0.0 V0.0\n"
        "\n"
        "UTC2026-06-20 14:03:20.000\n"
        "Frame2 SZ1 Yaw0 Pit0 fps30\n"
        "Deque3(V0.0,x0.0)(V0.0,x0.0)(V0.0,x0.0)\n"
        "Fast0\n"
        "FIN:x0.0 V0.0\n"
    )
    result = parse_track_file(_write(tmp_path, body))
    assert result.start_utc is not None
    assert result.start_utc.hour == 14 and result.start_utc.minute == 0
    # 200s between the two frames -> one recording gap (0, 200)
    assert len(result.gaps) == 1
    assert result.gaps[0][0] == 0.0
    assert abs(result.gaps[0][1] - 200.0) < 0.01
