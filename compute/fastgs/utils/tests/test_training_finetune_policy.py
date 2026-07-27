import pytest

from prune_gaussians import validate_finetune_iterations


def test_normal_prune_run_requires_finetuning():
    with pytest.raises(ValueError, match="positive"):
        validate_finetune_iterations(0, dry_run=False)


def test_dry_run_can_skip_finetuning():
    assert validate_finetune_iterations(0, dry_run=True) == 0


def test_normal_prune_run_keeps_requested_finetuning_iterations():
    assert validate_finetune_iterations(800, dry_run=False) == 800
