# Demo script (5 minutes)

Run beforehand: `make setup` once, then `make seed` to load stock data.
Start everything with `make sim` in one terminal and `make dashboard` in
another. Open the dashboard in a browser and keep the Live page up.

## 0. Framing (30s)

"StoreSmart turns a store's existing cameras into real-time intelligence —
without ever storing or sending a single frame. Everything you're about to
see is built from anonymous JSON events, computed on this laptop, standing
in for an edge box with a Qualcomm NPU."

Open the **Privacy** page first: point at "Images written to disk: 0" and
the live event feed. Click **"Inject fake image event"** — show it gets
rejected by the event gate.

## 1. Footfall & queue (60s)

Switch to **Live**. The simulator is already running: point at IN/OUT/inside
counters ticking up, the queue length, and the wait/forecast numbers. Wait
for (or manually trigger, by editing `--counters`) the **"open another
counter"** alert banner, and click **Acknowledge** on it.

Talking point: "The forecast already accounts for shoppers who are inside
the store but haven't reached the queue yet — that's the early-warning part."

## 2. Store map (60s)

Switch to **Store Map**. Show the shop-size fields and the rectangle table
(shelves/doors/counters/camera already filled in from the example config).
Point at the live anonymous dots moving on the preview — "these come from a
4-point homography that maps a person's foot position in the camera to feet
on this map; the dots are the only thing ever displayed, never the frame."

## 3. Shelves & stock (90s)

Switch to **Shelves & Stock**. Point at the slot grid — colors correspond to
backdrop-visibility percentage. Switch to **Billing**, sell a couple of
units of an item until its shelf slot would look empty; back on Shelves &
Stock, show the resulting **refill** alert appearing (dedup means it won't
spam). Point at the items table: days-left and order-by date, explicitly
labelled as based on simulated 30-day sales history.

## 4. Dwell & insights (60s)

Switch to **Dwell & Insights**. Show the heatmap (small-count suppression
means sparse cells stay hidden) and the dwell-per-zone table. Read one
rule-based suggestion aloud, e.g. "high sales, low dwell — consider moving
this item further back."

## 5. Close (30s)

Back to **Privacy**: total events, KB stored, 0 images. "Everything you saw
came from under a kilobyte per event, validated by a schema gate, never a
picture of a customer."

## Fallback if a phone/Wi-Fi issue happens live

Every module supports `--simulate`; `make sim` runs the whole system with
synthetic data with no camera at all. If phones misbehave mid-demo, say so
and switch to the simulate terminal already running in the background.
