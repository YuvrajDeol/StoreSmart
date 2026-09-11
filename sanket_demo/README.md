# Sanket demo — people counter + queue intelligence

Laptop + phone camera. Counts people crossing an entry line, measures the queue, forecasts wait time, and tells you when to open another counter. No image is ever saved.

## 1. Install (do this while you have internet)

Python 3.10+ recommended.

```bash
pip install -r requirements.txt
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"   # downloads the model once
```

After this, the demo runs fully offline.

## 2. Test without any camera

```bash
python sanket_demo.py --source simulate
```

The simulator runs a synthetic store. Arrivals surge after ~35 s, so you'll see the "OPEN ANOTHER COUNTER" alert. Press `+` to open a counter and watch the queue drain. This is also your backup if the camera fails on stage.

## 3. Connect the phone as a camera

| Phone | App | How to run |
|---|---|---|
| Android | IP Webcam | Tap "Start server". Use the URL shown in the app: `--source http://PHONE_IP:8080/video` |
| Android / iPhone | DroidCam | Wi-Fi mode: `--source http://PHONE_IP:4747/video`. Or install the DroidCam laptop client and use `--source 1` (webcam index) |
| iPhone + Mac | Continuity Camera | The iPhone appears as a webcam: try `--source 0` or `--source 1` |

- Phone and laptop must be on the same network. College Wi-Fi often blocks device-to-device traffic, so use the **phone's hotspot** with the laptop connected to it, or a USB mode (DroidCam/Iriun client).
- Keep the phone on a charger and turn off screen sleep.

## 4. Mount the phone

- High up (2 m or more), angled down, in landscape.
- One view that covers a "doorway" on one side and a "billing counter" area with space for a queue.
- Good, even lighting. Avoid a bright window behind people.

## 5. First run: place the line and zones

```bash
python sanket_demo.py --source http://PHONE_IP:8080/video
```

On first run, the raw camera view opens for setup:
1. Click 2 points for the **entry line** across the doorway.
2. Click the corners of the **queue zone**, then press Enter. Press `N` to skip queue analysis and run as a counter only.
3. Click the corners of the **counter/service zone** (where a customer stands while being billed), then press Enter.

The layout is saved to `sanket_config.json`. Press `s` any time to redo it. If IN and OUT are swapped, press `f`.

## 6. Keys

| Key | Action |
|---|---|
| `v` | Cycle views: people blurred → zero-frame (dots only) → raw (setup) |
| `+` / `-` | Open / close a billing counter |
| `f` | Flip which direction counts as IN |
| `r` | Reset counts |
| `s` | Redo line/zone setup |
| `q` | Quit |

## 7. Demo script (about 3 minutes, 5–6 people)

Set a volunteer as "cashier" standing beside the counter zone. Start in the **blurred** view.

1. **Footfall (30 s).** Three people walk in across the line one by one. IN goes up. One walks back out; OUT goes up. "The entrance counter is our early-warning signal."
2. **Predictive alert (60 s).** Four or five people walk in quickly and stand around, "browsing", away from the queue. Point to *Browsing* and *Forecast wait* rising. Within a few seconds: **OPEN ANOTHER COUNTER**, reason *forecast*, before any queue exists. "The system warns before the queue forms."
3. **Queue and service (45 s).** Everyone forms a line in the queue zone. One at a time, each steps into the counter zone for ~5 s, then walks out across the line. Watch *In queue*, *Avg service time* and *Est. wait* update.
4. **Staff action (15 s).** Press `+`. "The manager opened counter 2." The forecast drops and the alert clears.
5. **Privacy proof (30 s).**
   - Press `v` for the **zero-frame** view: "This is all the system needs — positions, not people."
   - In a second terminal, run `python listen_events.py` and start the demo with `--udp 127.0.0.1:9999`. "Every byte leaving the system is a tiny text event like this. Never an image."
   - Point to *Images written to disk: 0*, and open `events.jsonl` to show only small JSON lines.

Rehearse this at least twice in the actual room. Lighting and camera angle matter more than anything else.

## 8. Tuning (command-line options)

| Option | Default | Meaning |
|---|---|---|
| `--threshold` | 12 | Alert when current or forecast wait exceeds this many seconds |
| `--horizon` | 10 | How far ahead the forecast looks (seconds in the demo; minutes in a real store) |
| `--hold` | 3 | Condition must last this long before the alert turns on/off, so it doesn't flicker |
| `--default-service` | 6 | Assumed service time until real service times are measured |
| `--conf` | 0.35 | Detection confidence; raise if you get false detections |
| `--imgsz` | 640 | Use 480 on slow laptops for more FPS |
| `--device` | auto | `0` for an NVIDIA GPU, `mps` for Apple Silicon |

Example for a slow laptop:
```bash
python sanket_demo.py --source http://PHONE_IP:8080/video --imgsz 480
```

## 9. Troubleshooting

- **"No frames from the camera":** open the stream URL in a browser first. If that fails, it's a network issue — switch to the phone hotspot.
- **Laggy video:** the demo always processes the newest frame, but lower the app's resolution (720p is enough) and use `--imgsz 480`.
- **IN/OUT miscounts:** place the line where people cross cleanly and are fully visible. Increase `--margin` if jittery people get double-counted.
- **IDs keep changing:** improve lighting, move the camera higher, and make sure people don't overlap heavily.

## 10. Honest notes for judges' questions

- This prototype runs on a laptop CPU/GPU. The production target is the Qualcomm QCS6490 NPU, with models compiled to INT8 through Qualcomm AI Hub.
- Tracking uses ByteTrack, which associates detections by motion only. It stores no appearance features, so it cannot recognise anyone.
- The demo compresses minutes into seconds so the queue logic can be shown live. The forecast here is a transparent heuristic: shoppers already inside will reach checkout, minus what the counters can serve in the horizon. The production design uses a trained forecaster (LightGBM) and Erlang-C staffing.
- Frames exist only in memory. The code never writes an image. Only JSON events go to `events.jsonl` (and to UDP if enabled).
