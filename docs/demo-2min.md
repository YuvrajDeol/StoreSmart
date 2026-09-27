# StoreSmart — 2-minute demo

Five beats, four screens, no backtracking. About 280 spoken words, which is
all that fits in two minutes at a natural pace — so the words below are the
whole script, not notes to expand on.

Text in _[brackets]_ is an action, not something to say.

---

## Pre-flight — 10 minutes before

```bash
cd /Users/yuvraj/StoreSmart && bash scripts/demo_start.sh
```

Takes ~20 seconds. It clears old data, seeds the stock database, starts all
four phases, launches the dashboard, and waits until every phase is actually
reporting — so you open on a live store, not a warming-up screen. It prints
`READY → http://localhost:8520` plus a status line; if any phase is missing
there, run it again before you worry about anything else.

Then:

1. Open **http://localhost:8520**, full screen, browser zoom at 100%.
2. Leave it on the **hub** (the `app` page).
3. Put the **camera window** on a second desktop/space if you're doing the
   live version — `⌃→` to switch, so it's one gesture mid-demo.
4. **Silence notifications.**

**Decide the camera question now, not on stage.** Run the live counter once.
If people are detected and the count moves when you walk through, use
**Beat 2-Live**. If anything is off — network, line placement, nobody
detected — use **Beat 2-Safe** and don't apologise for it. Both are honest;
the deck already says phones stand in for CCTV.

---

## Beat 1 · The hub — 15s

_[Start on the hub. Don't scroll. Point with the cursor, don't click.]_

> This is StoreSmart — a whole store on one screen. Four AI modules running
> live, all on this laptop. Twelve people inside, a queue building, and it's
> already flagging what needs attention.

_[Cursor sweeps: the KPI row → the alert panel → the module list showing
"live".]_

---

## Beat 2 · It's real — 25s

### Beat 2-Live _[switch to the camera window]_

> This is a real camera — my phone, standing in for the store's CCTV. It's
> detecting people and counting them across the entrance line.
>
> Notice everyone is blurred. That blur isn't cosmetic: nothing outside this
> window ever receives the unblurred frame. Watch the count as I walk
> through.

_[Walk across the line. Count increments. Return to the browser.]_

### Beat 2-Safe _[click **Live** in the sidebar]_

> Behind this is a phone standing in for the store's CCTV, detecting people
> and counting them across the entrance line — running here on our simulator
> so it's reproducible.
>
> In and out, the queue, and the wait. And the forecast is the interesting
> one: it counts people at the entrance, so it warns you *before* they reach
> the counter — which is why that "open another counter" alert is already up.

---

## Beat 3 · Refill vs reorder — 30s

_[Click **Shelves St…** in the sidebar]_

> Shelf cameras watch the slots. Red is empty.
>
> But it doesn't just say "empty". It checks the storeroom and the billing
> data. Rice — you have stock in the back, so that's a **refill** task for
> staff. Sugar — the storeroom's empty too, so that's a **purchase order**,
> and it knows the supplier visits Wednesday, so it says order by Monday.

_[Point at one refill alert and one reorder alert as you say each.]_

> That's the difference between a task and a decision, and no one else makes
> it.

---

## Beat 4 · The billing loop — 20s

_[Click **Billing**, click one item button]_

> This is the billing link. I sell a packet of milk — stock drops, and that
> sale feeds the run-out forecast.
>
> No manual stock-taking. It rides on the POS software the shop already runs.

---

## Beat 5 · The privacy proof — 30s

_[Click **Privacy**]_

> And this is the part we'd want you to test.
>
> Images written to disk: zero. Everything this store knows is that number
> there — under a megabyte of text. One camera generates about **12.6
> gigabytes of video a day.**

_[Click **Inject fake image event**]_

> Let me try to break it. That injects an event carrying an image —
> rejected, and counted. The gate is enforced in code, with a test that
> fails the build if anyone adds an image-writing call.

_[Pause. Look up.]_

> Your cameras see the store. Nobody sees your customers.

---

## If something goes wrong

| Symptom | Do this, out loud, without stopping |
|---|---|
| Camera won't connect | "I'll show the simulated version" → Beat 2-Safe. Never debug on stage. |
| A number looks wrong | Keep going. Nobody is auditing arithmetic in 2 minutes. |
| Dashboard hangs | Reload the tab — state is in SQLite, nothing is lost. |
| You're running long | Cut Beat 4 entirely. Beat 5 is the one that must land. |
| Asked a question mid-demo | "Let me finish this in thirty seconds and come straight back." |

---

## Notes on delivery

- **Beat 5 is the demo.** Everything before it is setup for the moment the
  gate rejects the image. If you only get one beat, make it that one.
- **Don't read the screen aloud.** The numbers are visible; say what they
  *mean*.
- **Don't scroll the hub.** Everything you need is above the fold. Scrolling
  reads as hunting.
- **Don't open the Control page** during the demo. It's a setup tool and it
  invites questions about what's simulated.
- If they ask **"is this live or simulated?"** — answer plainly: the counter
  and queue run on a real camera, the shelf, map and dwell modules run on our
  simulator today and go on real cameras next. That answer builds credibility;
  hedging destroys it.

---

## Afterwards

```bash
bash scripts/demo_stop.sh
```
