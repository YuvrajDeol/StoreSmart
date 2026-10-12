import numpy as np

from edge_lab.explain import (candidate_bucket, grade, letterbox_image, letterbox_params,
                              letterbox_text, score_answer, Game)


def test_score_exact_close_wrong():
    assert score_answer(4, 4) == (100, "correct")
    assert score_answer(3, 4) == (50, "close")
    assert score_answer(5, 4) == (50, "close")
    assert score_answer(7, 4) == (0, "wrong")


def test_letterbox_1080p():
    p = letterbox_params(1920, 1080, 640)
    assert (p["new_w"], p["new_h"]) == (640, 360)
    assert (p["pad_x"], p["pad_y"], p["pad_b"]) == (0, 140, 140)
    assert abs(p["scale"] - 1 / 3) < 1e-9
    assert letterbox_text(1920, 1080, 640) == "1920x1080 -> 640x640, scale 0.33, pad 0,140"


def test_letterbox_portrait_and_image():
    p = letterbox_params(480, 640, 640)
    assert (p["new_w"], p["new_h"], p["pad_x"], p["pad_y"]) == (480, 640, 80, 0)
    img = letterbox_image(np.zeros((1080, 1920, 3), np.uint8), 640)
    assert img.shape == (640, 640, 3)
    assert (img[0, 0] == 114).all() and (img[320, 320] == 0).all()


def test_bucket_and_grade():
    assert candidate_bucket(34) == 7 and candidate_bucket(0) == 0 and candidate_bucket(500) == 9
    assert grade(300, {2: 100, 3: 100, 4: 100}) == "You understand the pipeline"
    assert "NMS" in grade(200, {2: 100, 3: 100, 4: 0})


def test_game_answers_once_and_scores():
    from edge_lab.shelf_watch import Det
    g = Game()
    g.stage = 3
    D = {"cand": [Det("cup", (0, 0, 1, 1), c) for c in (0.9, 0.6, 0.2)]}
    assert g.answer(2, D, 0.35)["verdict"] == "correct"
    assert g.answer(9, D, 0.35) is None and g.score == 100
