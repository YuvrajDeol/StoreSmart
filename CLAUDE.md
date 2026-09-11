# CLAUDE.md — StoreSmart privacy invariants

This file restates the non-negotiable rules for this repository. Any future
session (human or Claude) editing this codebase must follow them. If a change
would violate one of these, stop and flag it instead of implementing it.

## Zero-Frame Architecture

Video frames exist only in memory, only inside perception modules
(`storesmart/common/detector.py`, `storesmart/common/video.py`, and the
`*_sim.py` simulators). The only thing allowed to leave a perception module is
a validated JSON event (see contract below). Concretely:

- No `cv2.imwrite`, `cv2.VideoWriter`, `PIL.Image.save`, or any other call
  that writes an image/video to disk, anywhere in `storesmart/`, `scripts/`
  (outside `scripts/dev_only/`), or the dashboard.
- No image bytes, base64-encoded images, or embeddings inside an event or a
  log line.
- `tests/test_privacy_scan.py` greps the source tree for these patterns and
  fails the build if any appear outside `tests/` and `scripts/dev_only/`. Run
  it (`pytest tests/test_privacy_scan.py`) after touching any camera or
  detector code.

## No identity, only motion

Tracking is YOLOv8 (person class only) + ByteTrack, which associates boxes
frame-to-frame by motion/IoU — never by appearance. Do not add:

- face detection or face recognition
- appearance embeddings or re-identification (matching people across gaps by
  clothing/appearance)
- demographic inference (age, gender, etc.)

Track IDs are ephemeral integers scoped to a single camera's live session.
Never persist them beyond the live view or join them across cameras/sessions.

## Event contract

Every event is one of the shapes in `storesmart/common/events.py`
(`EventGate`/pydantic models, `extra="forbid"`, max 1 KB serialized). Modules
must call `EventBus.emit(dict)` — never write directly to the database — so
every event passes the gate. Rejected events are counted, not silently
dropped. The canonical shapes:

```json
{"t":"ISO-8601","cam":"entrance","type":"entry"}
{"t":"...","cam":"entrance","type":"exit"}
{"t":"...","cam":"counter","type":"queue","length":4,"serving":1,"counters":1,"wait_s":24.0,"forecast_wait_s":38.0}
{"t":"...","cam":"counter","type":"served","service_s":5.2}
{"t":"...","cam":"shelf","type":"shelf_status","slot":"A2","fill_pct":10,"state":"empty"}
{"t":"...","cam":"floor","type":"position","x_ft":12.5,"y_ft":6.0,"track":17}
{"t":"...","cam":"floor","type":"dwell","zone":"snacks","dwell_s":18.0}
{"t":"...","type":"alert","kind":"open_counter|refill|reorder|mismatch|layout","msg":"...","item":"optional","severity":"info|warn|urgent"}
{"t":"...","type":"summary","in":12,"out":9,"inside":3}
```

Adding a new event type means adding a new pydantic model to
`storesmart/common/events.py` and registering it in `EVENT_TYPES` — don't
just widen an existing model with `extra` fields.

## Small-count suppression

Any aggregate (dwell-per-zone, heatmap cell, etc.) must hide buckets with
fewer than `k` people, `k` configurable via `config/settings.yaml`
(`privacy.small_count_suppression_k`), default 5 in production, demo default
2. Never display an aggregate derived from fewer than `k` people.

## Setup screens

Screens that need to show a camera view for calibration (drawing the
entry line, shelf slots, homography points) must use the in-memory
people-free background from `storesmart.common.privacy.BackgroundEstimator`
(median of recent frames), never a frame saved to disk. Saved config files
store only coordinates/matrices, never pixels.

## Display views

Default display is `blurred` (people's bounding boxes Gaussian-blurred).
`zero-frame` (black canvas, dots only) must always be available as a toggle.
`raw` is allowed only during setup/calibration and must be visibly labelled
"RAW VIEW - setup only, nothing is saved".

## Offline-only

No CDN, external map tile service, or remote API call at runtime. Model
weights are downloaded once during `make setup`; everything else must work
with no network.

## Production target note

This demo runs on a MacBook (Apple Silicon, `device="mps"` with automatic
CPU fallback) with phones standing in for CCTV/shelf cameras. The production
target is an in-store edge box built on a Qualcomm QCS6490 NPU. Do not build
NPU-specific code now — `make coreml` (Core ML export) is the closest
stand-in for that deployment path in this demo.
