# How it works — object detection on the edge

Written for the Edge AI lab submission. Covers the pipeline end to end, the
model choice and why, and what else we could have used.

---

## 1. The pipeline

Both features in this project — people counting and shelf watching — run on
the same detection pipeline. Only what happens *after* detection differs.

```
camera frame                     1280x720 BGR, in memory only
      │
      ▼
preprocess                       letterbox to 640x640, BGR→RGB,
      │                          uint8 → float32, /255, HWC → CHW
      ▼
YOLOv8n forward pass             one pass, on the GPU (Apple MPS)
      │                          outputs ~8400 candidate boxes
      ▼
confidence filter                drop everything below conf (default 0.35)
      │
      ▼
non-maximum suppression (NMS)    merge overlapping boxes for the same object
      │
      ▼
scale boxes back                 640x640 coords → original frame coords
      │
      ├──► ByteTrack ──► line crossing ──► IN / OUT counts
      │
      └──► baseline match ──► item missing? ──► "TAKEN"
```

`edge_lab/explain.py` walks through these stages interactively — that's the
same pipeline, rendered one step at a time.

### Stage detail

**Preprocess.** The network has a fixed input size, so a 1280×720 frame has
to become 640×640. Plain resizing would squash people vertically, so we
*letterbox*: scale by the smaller ratio (640/1280 = 0.5) and pad the short
side with grey bars. Aspect ratio is preserved, and the padding offset is
subtracted later when mapping boxes back.

> Footnote worth knowing: Ultralytics' PyTorch path trims padding to a
> multiple of 32, so a 16:9 frame actually goes in as 640×384, not 640×640.
> A fixed-shape export (ONNX/CoreML/TFLite for an NPU) uses the full square.
> The explainer draws the square and says so.

**Forward pass.** One pass produces a dense grid of predictions — roughly
8400 candidate boxes for a 640×640 input, each with a box, an objectness
score and 80 class scores. The model does *not* "look for objects one at a
time"; it predicts the whole grid at once. That's what makes single-stage
detectors fast, and it's the key idea to convey in a viva.

**Confidence filter.** Most of those 8400 are near-zero confidence. We keep
those above a threshold. This is the precision/recall dial: lower it and you
catch more real objects but also more false positives.

**NMS.** One real object usually fires several neighbouring grid cells, so
you get a cluster of overlapping boxes. NMS keeps the highest-confidence box
and discards others overlapping it by more than an IoU threshold (0.45 here).
Stage 5 of the explainer shows the same frame at IoU 0.95 vs 0.45 so you can
see the duplicates collapse.

**Scale back.** Divide out the letterbox scale, subtract the padding, and the
boxes land on the original frame.

### What happens after detection

**People counting.** Boxes of class `person` go to **ByteTrack**, which
assigns each person a track ID and keeps it stable across frames by matching
predicted motion to new boxes (Kalman filter + IoU association). We take each
track's **foot point** — bottom-centre of the box — and watch which side of a
user-drawn line it's on. Cross from one side to the other and that's an entry
or an exit.

Two details that matter in practice, both learned the hard way:
- A **buffer band** either side of the line. A foot point must get clearly
  past the band on one side, then the other, before it counts. Without it,
  detection jitter at the line produces repeated phantom crossings.
- **ID-swap bridging.** ByteTrack reassigns an ID when it briefly loses
  someone. A new ID appearing near where one just vanished inherits its
  crossing state, so the crossing isn't lost.

**Shelf watching.** Boxes of retail-ish classes (bottle, cup, book, phone…)
are snapshotted as a *baseline*. Each later frame is matched against that
baseline by **same class + centroid within 12% of frame width**. An item with
no match for 5 consecutive frames is reported `TAKEN`. The 5-frame debounce is
the whole trick — a single dropped detection would otherwise fire a false
alert on every flicker.

---

## 2. The model: YOLOv8n

**What it is.** YOLOv8-nano, the smallest of the YOLOv8 family. ~3.2 M
parameters, ~8.7 GFLOPs at 640×640, trained on **COCO** (80 everyday object
classes — person, bottle, cup, book, cell phone, banana…).

**Measured here** (Apple M-series GPU via MPS, 640×640):

| | mean | p95 |
|---|---|---|
| inference | **9–16 ms** | 10–27 ms |
| end-to-end | **~40–65 FPS** | — |

### Why this model

1. **It fits the edge budget.** ~10 ms per frame leaves room for tracking,
   drawing and a second model stream while still clearing real-time. The next
   size up (YOLOv8s, ~11 M params) is roughly 2–3× the cost for accuracy we
   don't need to count whole people.
2. **COCO already contains our classes.** `person` for counting; `bottle`,
   `cup`, `book`, `cell phone` etc. for the shelf. **Zero training required** —
   a decisive advantage on a lab timescale.
3. **One model, two features.** Both windows run the same weights, just
   filtering different class IDs. Less to deploy, less to explain.
4. **It exports cleanly.** ONNX / CoreML / TFLite are one command, which is
   what makes the jump to real NPU hardware plausible rather than hypothetical.
5. **Tracking comes with it.** Ultralytics bundles ByteTrack, so we didn't
   write an associator.

### Why *nano* rather than a bigger variant

Accuracy on COCO (mAP50-95): n ≈ 37.3, s ≈ 44.9, m ≈ 50.2. The bigger models
are clearly better — but our task is "is there a person" and "is the bottle
still there", at close range, with large objects in frame. That's the easy end
of detection. Spending 3× the latency to better distinguish a sheep from a cow
buys us nothing. **If** we moved to small items on a dense retail shelf
(SKU-110K-style), that calculus flips.

---

## 3. Alternatives, and why not

### Other detectors

| Option | Trade-off | Verdict |
|---|---|---|
| **YOLOv8s/m/l** | 2–10× slower, meaningfully more accurate | Overkill for large close objects; revisit for dense shelves |
| **YOLOv5n** | Very similar speed, slightly lower accuracy, older | No reason to prefer it |
| **YOLO-NAS / YOLOv9/v10/v11** | Equal or better accuracy-per-FLOP | Reasonable swap; v8 chosen for mature tooling + bundled tracking |
| **MobileNet-SSD** | Faster on weak CPUs, notably worse accuracy | Would win if we had no GPU/NPU at all |
| **EfficientDet-Lite** | Good TFLite/Coral story | Weaker ecosystem for our stack |
| **Faster R-CNN** | Two-stage, more accurate on small objects | ~10× too slow; two-stage is the wrong family for real-time edge |
| **DETR / RT-DETR** | Transformer, no NMS needed (elegant) | RT-DETR is genuinely competitive; heavier, less mature on-device tooling |

### Other approaches to *shelf* monitoring specifically

- **Classical CV (HSV backdrop threshold)** — what this project used first.
  Measure how much known-coloured backdrop is visible per slot. Extremely
  cheap (no neural network, ~1 ms) and very reliable — *but* it needs fixed
  slot rectangles and a prepared plain backdrop, and it can only answer "is
  slot A2 empty". It cannot say *what* was taken. We replaced it for this
  reason; the code still exists in `storesmart/phase3_shelf/`.
- **Image differencing / background subtraction** — flag changed pixels.
  Cheapest of all, but triggers on lighting changes, shadows and people
  walking past, and again identifies nothing.
- **Fine-tuned detector on SKU-110K** — the production answer for real retail
  shelves with densely packed branded products. Needs labelled data and
  training time we don't have, and Indian retail packaging is extremely varied.
- **Planogram compliance models** — check the right product is in the right
  place, not merely present. A genuinely harder problem; out of scope.

### Other trackers

- **ByteTrack** (ours) — motion-only, associates by IoU + Kalman prediction,
  including low-confidence boxes. Fast and needs no appearance model.
- **SORT** — simpler, drops low-confidence detections, so worse through
  occlusion.
- **DeepSORT / StrongSORT / BoT-SORT** — add an appearance embedding, so they
  re-identify people after long gaps. More accurate through occlusion, **but
  deliberately rejected**: an appearance embedding is a biometric signature,
  which breaks this project's privacy rule that tracking must be motion-only.
  That is a design constraint, not an oversight.

---

## 4. Running it on real edge hardware

Today this runs on a MacBook GPU through **Apple MPS**, with automatic CPU
fallback. That is a stand-in for a dedicated edge device. The path to real
hardware:

| Target | Export | Notes |
|---|---|---|
| Apple Silicon / iPhone | **CoreML** (`make coreml`) | Already wired up; uses the Neural Engine |
| Qualcomm QCS6490 | ONNX → QNN, INT8 | ~12 TOPS; the production target in our SIH deck |
| NVIDIA Jetson | TensorRT, FP16/INT8 | Highest throughput per watt at the top end |
| Google Coral | TFLite, INT8 only | Cheapest; requires full quantisation |
| Raspberry Pi (CPU) | TFLite / NCNN | Works, but expect single-digit FPS at 640 |

**INT8 quantisation** is the main lever: roughly 4× smaller weights and 2–4×
faster, for typically 1–3 mAP of accuracy. For "is a person there", that
trade is clearly worth it.

---

## 5. Honest limitations

- **COCO classes only.** The shelf watcher recognises bottles and cups, not
  *Parle-G vs Britannia*. Real retail needs a fine-tuned model.
- **Centroid matching is naive.** Two identical bottles side by side can swap
  identity. IoU matching or a Hungarian assignment would be more robust.
- **No occlusion reasoning.** A hand over an item reads as "taken" until the
  debounce clears it.
- **Single camera, single view.** No multi-camera fusion or 3D reasoning.
- **Metrics are from this Mac.** Numbers on a QCS6490 or a Pi will differ
  substantially; we have not yet measured on either.

---

## 6. Likely viva questions

**Why one-stage rather than two-stage?** Two-stage (Faster R-CNN) proposes
regions then classifies them — more accurate on small objects, far too slow
for real-time edge. One-stage predicts the whole grid in a single pass.

**What actually is NMS, and why needed?** One object activates several
neighbouring grid cells, producing duplicate overlapping boxes. NMS keeps the
highest-scoring box and suppresses others overlapping it beyond an IoU
threshold. Stage 5 of the explainer shows this directly.

**Why the foot point rather than box centre?** The foot point is where the
person actually stands on the floor plane. A box centre sits at torso height
and shifts with posture and camera angle, so it crosses a floor line at the
wrong moment.

**What limits your FPS?** Inference dominates (~10 ms); preprocessing,
tracking and drawing are each ~1 ms. Running two model streams in `--mode
both` roughly halves FPS, which the measurements show.

**How would you improve accuracy without losing speed?** INT8 quantisation to
buy headroom, then spend it on a larger input size (640 → 960), which helps
small objects more than a bigger model would.
