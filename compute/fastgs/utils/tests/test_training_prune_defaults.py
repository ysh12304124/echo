from argparse import ArgumentParser

from arguments import OptimizationParams


def extract_optimization_options(argv=()):
    parser = ArgumentParser()
    params = OptimizationParams(parser)
    return params.extract(parser.parse_args(list(argv)))


def test_unsafe_training_pruning_is_disabled_by_default():
    options = extract_optimization_options()

    assert options.final_prune_interval == 0
    assert options.online_prune_interval == 0


def test_unsafe_training_pruning_requires_explicit_intervals():
    options = extract_optimization_options(
        ("--final_prune_interval", "3000", "--online_prune_interval", "1000")
    )

    assert options.final_prune_interval == 3000
    assert options.online_prune_interval == 1000
