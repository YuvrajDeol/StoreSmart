from storesmart.phase1_footfall.group_size import GroupSizeEstimator


def test_typical_width_estimates_one_person():
    estimator = GroupSizeEstimator()
    assert estimator.estimate(70) == 1  # matches the seeded default baseline


def test_double_width_estimates_two_people():
    estimator = GroupSizeEstimator()
    # first, calibrate the baseline with a few normal single-person widths
    for _ in range(5):
        estimator.estimate(60)
    assert estimator.estimate(120) == 2


def test_group_size_capped_at_max():
    estimator = GroupSizeEstimator(max_group_size=3)
    for _ in range(5):
        estimator.estimate(60)
    assert estimator.estimate(600) == 3  # absurdly wide box still capped


def test_narrow_box_never_rounds_below_one():
    estimator = GroupSizeEstimator()
    assert estimator.estimate(5) == 1


def test_baseline_only_updates_from_single_person_boxes():
    estimator = GroupSizeEstimator()
    for _ in range(5):
        estimator.estimate(60)  # calibrate to 60px singles
    estimator.estimate(600)  # a merged/absurd box — must NOT pollute the baseline
    # baseline should still be ~60, so a normal single width still reads as 1
    assert estimator.estimate(65) == 1
