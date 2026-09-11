from storesmart.phase1_footfall.group_size import GroupSizeEstimator


def test_calibration_phase_always_counts_one(tmp_path=None):
    """With no baseline yet, every width during the calibration window is
    assumed to be a single person — this is what prevents the very first
    crossing (at whatever resolution this camera happens to be) from being
    misjudged and permanently poisoning the baseline."""
    estimator = GroupSizeEstimator(min_samples_before_estimating=5)
    for width in (400, 20, 9000, 1):  # wildly different scales, still all "1" during calibration
        assert estimator.estimate(width) == 1


def test_double_width_estimates_two_people_after_calibration():
    estimator = GroupSizeEstimator(min_samples_before_estimating=5)
    for _ in range(5):
        estimator.estimate(300)  # calibrate to this camera's real single-person width
    assert estimator.estimate(600) == 2


def test_group_size_capped_at_max():
    estimator = GroupSizeEstimator(max_group_size=3, min_samples_before_estimating=5)
    for _ in range(5):
        estimator.estimate(300)
    assert estimator.estimate(3000) == 3  # absurdly wide box still capped


def test_narrow_box_never_rounds_below_one():
    estimator = GroupSizeEstimator(min_samples_before_estimating=5)
    for _ in range(5):
        estimator.estimate(300)
    assert estimator.estimate(5) == 1


def test_baseline_only_updates_from_single_person_boxes():
    estimator = GroupSizeEstimator(min_samples_before_estimating=5)
    for _ in range(5):
        estimator.estimate(300)  # calibrate to 300px singles
    estimator.estimate(3000)  # a merged/absurd box — must NOT pollute the baseline
    # baseline should still be ~300, so a normal single width still reads as 1
    assert estimator.estimate(310) == 1


def test_high_resolution_camera_does_not_miscount_from_the_start():
    """Regression test: a high-res phone stream where a single person's box
    is e.g. 400px wide must not be misjudged against a low-res assumption —
    there is no hardcoded pixel default to get wrong in the first place."""
    estimator = GroupSizeEstimator(min_samples_before_estimating=3)
    for _ in range(10):
        assert estimator.estimate(400) == 1
