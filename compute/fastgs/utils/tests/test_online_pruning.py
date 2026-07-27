import unittest

import torch

from utils.pruning_utils import online_prune_mask


class OnlinePruneMaskTests(unittest.TestCase):
    def test_removes_low_opacity_far_and_oversized_gaussians(self):
        xyz = torch.tensor([
            [0.0, 0.0, 0.0],
            [0.1, 0.0, 0.0],
            [9.0, 0.0, 0.0],
            [0.2, 0.0, 0.0],
        ])
        scaling = torch.tensor([
            [0.1, 0.1, 0.1],
            [0.1, 0.1, 0.1],
            [0.1, 0.1, 0.1],
            [1.0, 0.1, 0.1],
        ])
        opacity = torch.tensor([[0.9], [0.01], [0.9], [0.9]])
        camera_centers = torch.tensor([[0.0, 0.0, 0.0]])

        mask = online_prune_mask(
            xyz, scaling, opacity, camera_centers,
            scene_extent=5.0,
            min_opacity=0.05,
            margin=1.2,
            max_scale_ratio=0.1,
        )

        self.assertEqual(mask.tolist(), [False, True, True, True])

    def test_uses_nearest_camera_not_camera_centroid(self):
        xyz = torch.tensor([[10.0, 0.0, 0.0]])
        scaling = torch.tensor([[0.1, 0.1, 0.1]])
        opacity = torch.tensor([[0.9]])
        camera_centers = torch.tensor([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]])

        mask = online_prune_mask(
            xyz, scaling, opacity, camera_centers,
            scene_extent=1.0,
            min_opacity=0.05,
            margin=1.2,
            max_scale_ratio=0.1,
        )

        self.assertEqual(mask.tolist(), [False])


if __name__ == "__main__":
    unittest.main()
