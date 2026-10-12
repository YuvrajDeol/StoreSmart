# StoreSmart Edge Lab

A cut-down, self-contained build of StoreSmart for an Edge AI lab. It shows two things only:

1. **People counting** - YOLOv8 (person class) + ByteTrack, with a virtual entry line and buffer band.
2. **Shelf gap detection** - per-slot fill % classified ok / low / empty (green / amber / red).

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

Keys: `q` quit, `v` toggle blurred / raw people boxes. The entry line is a vertical line down the middle of the
webcam view; walk across it to count IN / OUT. First camera use: allow Camera access for your Terminal in macOS
Privacy settings.

## Metrics HUD

- **Model / Device / Input size** - weights, `mps` or `cpu`, and YOLO `imgsz`.
- **Inference mean / p95** - measured time of a real YOLOv8 forward pass + ByteTrack per frame (last 120 frames,
  after a warm-up). p95 shows worst-case jitter. Never faked: if no model ran, the HUD shows "NO MODEL RAN".
- **FPS** - end-to-end processed frames per second (rolling), including drawing prep.
- **People (YOLO)** - persons YOLO detected in the current frame. **Gap detector** - classical CV time (not a neural net).

With `--simulate`, YOLO runs on the synthetic frames (so latency is genuine), but people *counting* uses the
simulator's scripted tracks so the demo still produces IN/OUT; the HUD labels the source "SIMULATED". Use
`--no-yolo-on-sim` to skip the model; the HUD then says so explicitly.

## Privacy

Frames exist only in memory. Nothing is written to disk (no image/video saving), and there is no face recognition,
appearance embedding or demographic inference. Track IDs are ephemeral.
