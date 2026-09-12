# StoreSmart

**Privacy-first, real-time store intelligence from a store's existing cameras — no frame is ever stored or sent.**

Built for Smart India Hackathon 2026, problem statement **SIH26179** (Qualcomm:
edge-AI retail intelligence).

## The problem, the solution

Small and mid-size retail stores have CCTV but no way to turn it into
actionable intelligence — queue buildup goes unnoticed, shelves run empty
without anyone knowing, and layout decisions are guesswork. Sending video to
the cloud for analytics is a privacy and bandwidth non-starter for a shop
floor full of customers.

StoreSmart runs all AI on an in-store edge device. Video is converted into
anonymous text events **in memory** and never stored or sent — the **Zero-
Frame Architecture**. For this demo, phones act as cameras (streaming over
Wi-Fi) and a MacBook (Apple Silicon) acts as the edge device; the production
target is a Qualcomm QCS6490 NPU.

## Architecture

```mermaid
flowchart LR
    Cams[Phones\n(entrance/counter/floor/shelf)] --> Perception[Perception modules\nframes in memory only]
    Perception -- "JSON events only" --> Gate{{Event Gate\nschema + size limit}}
    Gate --> Bus[(SQLite event bus)]
    Bus --> Dashboard[Streamlit dashboard]
    Stock[(Stock/billing DB)] --> Dashboard
    Bus --> Rules[refill/reorder/mismatch rules]
    Stock --> Rules --> Bus
```

See [docs/architecture.md](docs/architecture.md) for the full diagram and
module breakdown, and [docs/event-contract.md](docs/event-contract.md) for
every event shape.

## Quick start

```bash
make setup   # venv + deps + downloads yolov8n.pt once
make sim     # runs all phases with synthetic data, no camera needed
make dashboard   # in another terminal
```

Then open the URL Streamlit prints (usually http://localhost:8501).

On macOS you'll be prompted once for camera/network permissions if you run
with real phones instead of `--simulate` — allow Terminal (or your IDE)
camera and local-network access when asked, and check your Mac's firewall
isn't blocking incoming connections from the phone's IP.

## The four phases

1. **Footfall & queue** — entry/exit counting (either line-crossing, or a
   click-to-draw doorway rectangle where entering it counts as IN and
   leaving it counts as OUT — see `--counting-mode doorway`), queue length,
   service time, wait forecast (from shoppers already inside), and an
   open-another-counter recommendation with hysteresis.
2. **Store map** — sketch shelves/doors/counters/cameras by click-and-drag
   on a to-scale canvas, optionally tracing an uploaded floor-plan image, with
   camera facing/field-of-view arrows for layout planning; a 4-point
   homography maps the floor camera's foot points onto it, shown as live
   anonymous dots.
3. **Shelf gaps + stock** — poll a shelf snapshot, detect empty slots via a
   white-backdrop HSV threshold, and combine that with a SQLite stock DB for
   refill-from-storeroom vs order-from-distributor reminders, run-out
   forecasts, and stock-mismatch alerts.
4. **Dwell zones & layout insights** — time spent per map zone, a heatmap,
   and rule-based suggestions combining dwell with sales per category.

## Phone setup (stand-in for CCTV)

Put your phone and laptop on the same Wi-Fi (a phone hotspot works well and
avoids router client-isolation issues).

- **IP Webcam (Android)**: install, start server, note the shown URL. Use
  `http://<phone-ip>:8080/video` for a live stream, `.../shot.jpg` for a
  snapshot (used for the shelf camera).
- **DroidCam**: `http://<phone-ip>:4747/video`.

Put real IPs in `config/cameras.local.yaml` (gitignored) — never commit them.
Mount the shelf phone so its shot fills the slot area against a plain
backdrop; mount the floor phone high enough to see full foot traffic for
calibration.

## Demo script

See [docs/demo-script.md](docs/demo-script.md) for a 5-minute, phase-by-phase
walkthrough with talking points.

## Privacy

Enforced in code and tests, not just policy — see [CLAUDE.md](CLAUDE.md) for
the full list:

- No image or video is ever written to disk or sent anywhere by any runtime
  module — enforced by `tests/test_privacy_scan.py`, which scans the source
  tree for `cv2.imwrite`/`VideoWriter`/`imencode` calls.
- Frames exist only in memory, inside perception code. Only JSON events
  leave a module, through a pydantic schema gate (`extra="forbid"`, max 1 KB,
  whitelisted types) — proven by a test that an image-bearing event is
  rejected.
- Tracking is motion-only (YOLOv8 person class + ByteTrack). No face
  detection, face recognition, appearance embeddings, re-identification, or
  demographic inference anywhere.
- Small-count suppression hides any dwell/heatmap bucket with fewer than `k`
  people (default 5 in production, 2 for this demo).
- Setup/calibration screens use an in-memory, people-free median background,
  never a saved photo.
- Display defaults to people blurred; a zero-frame (dots-only) view is
  always available; a raw view is allowed only during setup and is clearly
  labelled.
- Fully offline once model weights are downloaded — no CDNs, map tiles, or
  remote APIs at runtime.

## Limitations (stated honestly)

- Phones stand in for CCTV, and this MacBook stands in for the Qualcomm
  QCS6490 edge box the production system targets.
- Shelf gap detection uses a white-backdrop HSV threshold for demo
  reliability; production would use a trained shelf-emptiness model that
  works against any backdrop.
- Sales history in the stock DB is simulated (`make seed`), not real POS
  data.
- The run-out forecast is a transparent heuristic (average daily demand x
  weekday factor), not a trained time-series model — chosen so it's easy to
  explain and trust, not because it's the most accurate approach possible.

## Repository layout

See the module-by-module breakdown in
[docs/architecture.md](docs/architecture.md). Top level:

```
storesmart/     application code (common/, phase1-4, stock/, sim/, dashboard/)
config/         camera roles, settings, map/slot examples
scripts/        run_all.sh, check_privacy.sh, dev_only/
tests/          pytest suite (geometry, event gate, forecast, gap detector, dwell, privacy scan)
docs/           architecture, event contract, demo script
data/           gitignored — SQLite DB lives here
```

## Team / credits

- Team: _add your team name here_
- Members: _add names here_

## License

MIT — see [LICENSE](LICENSE).
