from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from reconstruct_images import poses_text_from_colmap_images


def test_poses_text_from_colmap_images_writes_sorted_c2w_rows():
    images = {
        "frame_000001.jpg": {
            "qvec": [1.0, 0.0, 0.0, 0.0],
            "tvec": [1.0, 2.0, 3.0],
        },
        "frame_000000.jpg": {
            "qvec": [1.0, 0.0, 0.0, 0.0],
            "tvec": [4.0, 5.0, 6.0],
        },
    }

    output = poses_text_from_colmap_images(images, ["frame_000000.jpg", "frame_000001.jpg"])

    rows = output.splitlines()
    assert len(rows) == 2
    assert len(rows[0].split()) == 16
    assert rows[0].split()[3] == "4.000000000000000"
    assert rows[0].split()[7] == "5.000000000000000"
    assert rows[0].split()[11] == "6.000000000000000"


def test_poses_text_from_colmap_images_rejects_unregistered_image():
    try:
        poses_text_from_colmap_images(
            {"frame_000000.jpg": {"qvec": [1.0, 0.0, 0.0, 0.0], "tvec": [0.0, 0.0, 0.0]}},
            ["frame_000000.jpg", "frame_000001.jpg"],
        )
    except ValueError as exc:
        assert "frame_000001.jpg" in str(exc)
    else:
        raise AssertionError("expected unregistered image to be rejected")
