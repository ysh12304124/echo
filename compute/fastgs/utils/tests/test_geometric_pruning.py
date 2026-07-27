import unittest

import torch

from utils import geometric_pruning
from utils.geometric_pruning import build_geometric_prune_decision, knn_isolation_mask, project_points


class GeometricPruningTests(unittest.TestCase):
    def test_project_points_returns_pixel_and_camera_depth(self):
        xyz = torch.tensor([[0.0, 0.0, 2.0], [1.0, 0.0, 2.0], [0.0, 0.0, -1.0]])
        rotation = torch.eye(3)
        translation = torch.zeros(3)

        uv, depth, valid = project_points(
            xyz, rotation, translation, fx=100.0, fy=100.0, cx=50.0, cy=40.0,
            width=100, height=80,
        )

        torch.testing.assert_close(uv[0], torch.tensor([50.0, 40.0]))
        torch.testing.assert_close(depth[:2], torch.tensor([2.0, 2.0]))
        self.assertEqual(valid.tolist(), [True, False, False])

    def test_requires_geometry_evidence_and_low_render_value(self):
        importance = torch.cat((torch.tensor([0.01, 0.01, 0.01, 3.0, 0.9]), torch.full((95,), 2.0)))
        visibility = torch.cat((torch.tensor([1, 2, 2, 1, 1]), torch.ones(95, dtype=torch.long)))
        support = torch.cat((torch.tensor([0, 0, 1, 0, 2]), torch.ones(95, dtype=torch.long)))
        conflicts = torch.cat((torch.tensor([2, 0, 0, 2, 2]), torch.zeros(95, dtype=torch.long)))
        isolated = torch.cat((torch.tensor([False, True, True, True, True]), torch.zeros(95, dtype=torch.bool)))

        decision = build_geometric_prune_decision(
            importance, visibility, support, conflicts, isolated,
            max_prune_ratio=0.03, importance_quantile=0.6,
        )

        self.assertTrue(decision["prune_mask"][0].item())
        self.assertTrue(decision["prune_mask"][1].item())
        self.assertFalse(decision["prune_mask"][2].item())
        self.assertFalse(decision["prune_mask"][3].item())
        self.assertFalse(decision["prune_mask"][4].item())

    def test_pruning_is_capped(self):
        count = 100
        importance = torch.arange(count, dtype=torch.float32)
        visibility = torch.zeros(count, dtype=torch.long)
        support = torch.zeros(count, dtype=torch.long)
        conflicts = torch.full((count,), 2, dtype=torch.long)
        isolated = torch.zeros(count, dtype=torch.bool)

        decision = build_geometric_prune_decision(
            importance, visibility, support, conflicts, isolated,
            max_prune_ratio=0.03, importance_quantile=0.5,
        )

        self.assertEqual(int(decision["prune_mask"].sum()), 3)
        self.assertEqual(decision["prune_mask"].nonzero().flatten().tolist(), [0, 1, 2])

    def test_scale_normalized_knn_preserves_large_sparse_gaussian(self):
        xyz = torch.tensor([
            [0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0],
            [1.0, 0.0, 0.0], [3.0, 0.0, 0.0],
        ])
        scaling = torch.tensor([
            [1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0],
            [0.1, 0.1, 0.1], [30.0, 30.0, 30.0],
        ])

        isolated, _, _ = knn_isolation_mask(xyz, knn_k=1, mad_factor=4.0, scaling=scaling)

        self.assertTrue(isolated[3].item())
        self.assertFalse(isolated[4].item())

    def test_screen_overlap_marks_only_dominated_depth_consistent_candidate(self):
        uv = torch.tensor([[10.0, 10.0], [11.0, 10.0], [50.0, 50.0]])
        depth = torch.tensor([2.0, 2.02, 2.0])
        radii = torch.tensor([3.0, 3.0, 2.0])
        importance = torch.tensor([1.0, 3.0, 1.0])

        losers = geometric_pruning.screen_overlap_loser_mask(
            uv, depth, radii, importance,
            depth_absolute_tolerance=0.05,
            depth_relative_tolerance=0.0,
            dominance_ratio=1.5,
            max_neighbors=4,
        )

        self.assertEqual(losers.tolist(), [True, False, False])

    def test_screen_overlap_redundancy_can_prune_supported_low_value_gaussian(self):
        count = 100
        importance = torch.cat((torch.tensor([0.01]), torch.full((count - 1,), 2.0)))
        visibility = torch.full((count,), 3, dtype=torch.long)
        support = torch.ones(count, dtype=torch.long)
        conflicts = torch.zeros(count, dtype=torch.long)
        isolated = torch.zeros(count, dtype=torch.bool)
        overlap = torch.zeros(count, dtype=torch.long)
        overlap[0] = 3

        decision = build_geometric_prune_decision(
            importance, visibility, support, conflicts, isolated,
            max_prune_ratio=0.03, importance_quantile=0.05,
            screen_overlap_count=overlap, min_overlap_views=3,
        )

        self.assertTrue(decision["redundant"][0].item())
        self.assertTrue(decision["prune_mask"][0].item())

    def test_voxel_cap_prevents_concentrated_pruning(self):
        count = 100
        importance = torch.arange(count, dtype=torch.float32)
        visibility = torch.full((count,), 3, dtype=torch.long)
        support = torch.ones(count, dtype=torch.long)
        conflicts = torch.zeros(count, dtype=torch.long)
        isolated = torch.zeros(count, dtype=torch.bool)
        overlap = torch.full((count,), 3, dtype=torch.long)
        xyz = torch.zeros((count, 3))

        decision = build_geometric_prune_decision(
            importance, visibility, support, conflicts, isolated,
            max_prune_ratio=0.03, importance_quantile=0.5,
            screen_overlap_count=overlap, min_overlap_views=3,
            xyz=xyz, voxel_size=1.0, max_voxel_prune_ratio=0.01,
        )

        self.assertEqual(int(decision["prune_mask"].sum()), 1)
        self.assertEqual(decision["prune_mask"].nonzero().flatten().tolist(), [0])

    def test_test_cameras_are_preferred_for_psnr(self):
        cameras, split = geometric_pruning.select_evaluation_cameras(["train"], ["test"])

        self.assertEqual(cameras, ["test"])
        self.assertEqual(split, "test")


if __name__ == "__main__":
    unittest.main()
