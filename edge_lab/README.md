# StoreSmart Edge Lab

A cut-down, self-contained build of StoreSmart for an Edge AI lab. It shows two things only:

1. **People counting** - YOLOv8 (person class) + ByteTrack, with a virtual entry line and buffer band.
2. **Shelf watch** - YOLO object detection over retail-plausible COCO classes (`SHELF_CLASSES` in `shelf_watch.py`); a baseline snapshot is compared to the live scene and an item that disappears is flagged TAKEN.

The focus is **object detection running on-device**, so a metrics HUD is always on screen.
Both features reuse the main `storesmart` modules; the event bus is replaced by an in-memory stand-in (no SQLite).

## Run

    # lab demo: Mac built-in webcam (default --source 0), real YOLO on-device
    .venv/bin/python -m edge_lab.app --mode both
    # no camera? synthetic scenes, but YOLO still runs for real on them
    .venv/bin/python -m edge_lab.app --mode both --simulate
    # phone MJPEG camera instead
    .venv/bin/python -m edge_lab.app --source http://PHONE_IP:8080/video --rotate 90
    # testable without a GUI
    .venv/bin/python -m edge_lab.app --simulate --headless --duration 5

`--mode both` opens TWO separate windows side by side ("Edge AI - People Counter", "Edge AI - Shelf Watch"), each with its own metrics HUD; `--mode people` / `shelf` open one.

Keys: `q` quit, `v` toggle blurred / raw people boxes, `l` redraw the entry line, `b` set the shelf baseline.

**Entry line (people window):** on first run click 2 points for the line, then 1 point on the OUTSIDE side. It is saved to `edge_lab/line.json` (coordinates only) and loaded on later runs; press `l` to redraw. The buffer band and foot-point dots are drawn as before.

**Shelf watch:** put items (bottle, cup, banana, phone, book...) in view. After ~2 s of stable detections the baseline is set automatically (or press `b`). Green box = present, red "TAKEN" box = removed from its baseline spot. Matching is same class + centroid within ~12% of frame width. Debounced both ways (5 frames to report TAKEN, 5 to report returned) so one dropped YOLO detection never fires an alert. Recent events are shown in the corner. First camera use: allow Camera access for your Terminal in macOS
Privacy settings.

## Metrics HUD

- **Model / Device / Input size** - weights, `mps` or `cpu`, and YOLO `imgsz`.
- **Inference mean / p95** - measured time of a real YOLOv8 forward pass + ByteTrack per frame (last 120 frames,
  after a warm-up). p95 shows worst-case jitter. Never faked: if no model ran, the HUD shows "NO MODEL RAN".
- **FPS** - end-to-end processed frames per second (rolling), including drawing prep.
- **People (YOLO)** - persons YOLO detected in the current frame. **Detections** - shelf objects found by YOLO in the current frame.

With `--simulate`, YOLO runs on the synthetic frames (so latency is genuine), but people *counting* uses the
simulator's scripted tracks so the demo still produces IN/OUT; the HUD labels the source "SIMULATED". Use
`--no-yolo-on-sim` to skip the model; the HUD then says so explicitly.

## Privacy

Frames exist only in memory. Nothing is written to disk (no image/video saving), and there is no face recognition,
appearance embedding or demographic inference. Track IDs are ephemeral.

Note: in `--simulate` the shelf scene is a synthetic picture with no real COCO objects, so YOLO finds none there; use a webcam with real items to see TAKEN events. Logic is covered by `tests/test_shelf_watch.py`.
