# StoreSmart — presentation script (6 slides)

Timed for **8 minutes**. A 3-minute cut is marked at the end. Text in
_[brackets]_ is a stage direction, not something to say.

A note before you start: the deck describes the **production system**
(QCS6490, LightGBM, React, Android, MQTT, POS integrations). The prototype
running today is Python on a MacBook with phones as cameras. Judges reward
that distinction and punish blurring it — the script keeps the two separate
throughout. Say "the prototype does X today; production targets Y."

---

## Slide 1 — Title (20 seconds)

> Good morning. We're team StoreSmart, problem statement SIH26179.
>
> One line before the slides: **your cameras should see the store, not your
> customers.** Everything we've built follows from that.

_[Move on quickly — don't read the problem statement aloud, they have it.]_

---

## Slide 2 — Idea (2 minutes)

**The problem (~30s)**

> Walk into any kirana store or supermarket today and three things are going
> wrong at once, invisibly.
>
> A shelf went empty an hour ago and nobody noticed. A queue formed at the
> counter, and the second counter opens only *after* customers are already
> annoyed. And the owner — who has CCTV running all day — has no idea how many
> people came in, or where they spent their time.
>
> The existing answer is cloud video analytics. That means uploading footage of
> your customers to someone else's servers. For an Indian retailer under the
> DPDP Act, that's a liability, not a product.

**The solution (~40s)**

> StoreSmart is an edge AI box that plugs into the CCTV a store already has,
> plus a few low-cost shelf cameras.
>
> The important part is what it does with the video: **frames are turned into
> anonymous text events inside the box, in milliseconds, and then discarded.**
> No video is stored. No video leaves. We call it the **Zero-Frame
> Architecture**, and it's verifiable — a judge can inspect our event log and
> find nothing but counts and timestamps.

**The four modules (~30s)** _[point, don't read every word]_

> Four things run on that box.
>
> **Footfall and queues** — who came in, how long the wait is, and an alert to
> open a counter *before* the queue forms.
> **Store map** — the owner sketches their shop; the system learns the layout.
> **Shelf and stock** — detects gaps on the shelf, and combines that with the
> billing data to tell you what to refill and what to reorder.
> **Dwell and layout** — where shoppers actually spend time, and what to do
> about it.

**What makes it different (~20s)**

> Three things we'd point to as genuinely novel.
>
> First, the queue alert is **predictive** — it counts people at the entrance,
> so it warns you before they reach the counter, not after.
> Second, we distinguish **restock from reorder**: an empty shelf with stock in
> the storeroom is a staff task; an empty shelf with an empty storeroom is a
> purchase order, timed against when the supplier actually visits.
> Third, **setup takes ten minutes** and needs no technical skill — the owner
> sketches the shop, the system refines it.

---

## Slide 3 — Technical approach (1.5 minutes)

**The flow (~45s)** _[trace the diagram left to right with your hand]_

> Follow the arrow. Cameras on the left — existing CCTV over RTSP, plus shelf
> cameras.
>
> They feed a **sealed perception box**. Pixels go in, detections come out, and
> the frame is deleted. Nothing downstream of that box has ever seen an image.
>
> Then the **schema gate**. This is the part we're proudest of: every event has
> to pass a strict schema before it's allowed to persist — a whitelist of event
> types, a size limit, no free-form fields. If a bug ever tried to smuggle an
> image out as an event, the gate rejects it and counts the rejection. That's
> not a policy document, it's enforced in code, and we have a test that fails
> the build if anyone adds an image-writing call.
>
> After the gate it's just text — a few kilobytes of counts in SQLite, feeding
> the dashboard, phone alerts, and billing sync.

**The methods (~30s)**

> The methods are deliberately explainable rather than exotic.
>
> Footfall is overhead detection plus line crossing. Queue wait uses **Little's
> law**, with Erlang-C for the staffing recommendation. Shelf gaps are measured
> as a gap percentage against a reference photo. Run-out forecasting is average
> demand adjusted for the weekday, worked backwards from the supplier's next
> visit and lead time.
>
> A shopkeeper can follow every one of those. That matters more than accuracy
> at the third decimal place, because they have to trust it enough to act on it.

**Tracking and privacy (~15s)**

> Tracking is **motion-only** — ByteTrack, which follows a box frame to frame by
> where it moved. There is no face detection, no appearance matching, no
> recognising someone across visits. It is architecturally incapable of it.

---

## Slide 4 — Feasibility and viability (1.5 minutes)

**Feasibility (~40s)**

> Technically this is settled. The QCS6490 gives us up to **12 TOPS** — far more
> than we need for a handful of camera streams. The models are open and the
> datasets are public: CrowdHuman for people, SKU-110K for retail shelves.
> Qualcomm AI Hub handles INT8 quantisation.
>
> Operationally, the key decision is that we **reuse the CCTV that's already
> installed**. No rewiring, no new cameras at the entrance. And it works fully
> offline — which in Tier-II and Tier-III retail is a requirement, not a
> feature.
>
> Economically, we tier it: a lite version for a kirana store, a fuller one for
> supermarkets, a chain dashboard above that. Shelf cameras only go on the top
> three to five aisles, which is where the money actually is.

**What's already built (~20s)** _[this is the credibility moment — be exact]_

> This isn't only a slide deck. We have a working prototype: the **people
> counter and queue prediction run live**, and we can demo them right now with
> phones standing in for the CCTV. The shelf, stock and dwell modules run on our
> simulator today, and go on real cameras next.

**Risks (~30s)** _[pick three, don't read all seven]_

> The risks worth naming:
>
> **Crowding and occlusion** at the entrance — handled with an overhead camera
> angle and head detection rather than full-body.
> **Indian packaging** is wildly varied, sachets and all — so we deliberately
> **detect gaps, not brands**. We never have to recognise a product, only
> notice that space is empty. That sidesteps the hardest problem in retail CV.
> **Stock data entry**, which is what kills most inventory products — solved by
> integrating with the billing software the store already uses, plus OCR on
> supplier invoices.
>
> And one we'd flag ourselves: the store's existing DVR still records video. We
> don't change that. What we guarantee is that **we** add no new access — our
> cameras are locked to our box.

---

## Slide 5 — Impact and benefits (1.5 minutes)

**The numbers (~30s)** _[lead with these, they're the strongest thing on the slide]_

> Four numbers.
>
> **1.7 trillion dollars** is lost globally every year to out-of-stocks and
> overstocks. That's the problem we're pointed at.
> **13 million** kirana stores in India; 88% of retail is unorganised. That's
> the market nobody has built for.
> **100 million** new organised-retail consumers in Tier-II and Tier-III cities
> by 2030.
> And the one that captures our architecture: a single camera generates
> **12.6 GB of video a day**. We reduce that to **a few megabytes of text.**

**Who benefits (~30s)**

> The **owner** gets fewer stock-outs and their first real shopper insight.
> **Shoppers** get shorter queues and items in stock — and are never tracked or
> profiled. **Staff** get a clear task list, and explicitly *not* individual
> performance monitoring, which is how these systems usually get used and why
> they get resented. And **local CCTV installers** get a new service line, which
> is also our distribution channel.

**The never-do list (~30s)** _[slow down — this is your closing argument]_

> I want to end this slide on the bottom line, because it's the commitment we'd
> ask to be held to.
>
> StoreSmart will **never** do face recognition. Never track a customer across
> visits. Never guess age or gender. Never store video. Never monitor an
> individual employee.
>
> Those aren't settings we chose to switch off. The system has no way to do
> them, and our tests fail if someone tries to add one.

---

## Slide 6 — Research and references (45 seconds)

> Briefly, what we built on.
>
> Market sizing from **IHL Group**, **Invest India** and **IBEF**. The privacy
> design is written against the **DPDP Act 2023** and the **2025 Rules** — whose
> core obligations bite in **May 2027**, which is exactly why a privacy-first
> architecture is worth building now rather than retrofitting later.
> Technically: **ByteTrack** for motion-only tracking, **SKU-110K** and
> **CrowdHuman** for data, Qualcomm's own AI Hub and RB3 Gen 2 documentation.
> Methods from classical queueing theory — **Little's law** and **Erlang-C**.

**Close (~20s)** _[the comparison table is the last thing they see — use it]_

> And the comparison, which is the whole pitch in one table.
>
> Cloud video analytics doesn't work offline and usually uploads your video.
> Manual checks work offline but predict nothing. StoreSmart is the only column
> that is offline, predictive, **and never stores video.**
>
> Your cameras see the store. Nobody sees your customers. Thank you — happy to
> demo it live.

---

## Anticipated questions

**"How is this different from existing people counters?"**
> Counting is the commodity part. Two differences: we predict the queue from
> entrance footfall instead of reacting to the counter, and we tie shelf gaps to
> the billing data so the alert says *refill from the storeroom* or *order from
> the distributor* — a different person, a different action.

**"Can you prove no video is stored?"** _[your best question — invite it]_
> Yes, live. Our dashboard has a privacy page showing every event in the
> database and a counter reading "images written to disk: zero". There's a
> button that injects a fake event carrying an image, and you can watch the
> schema gate reject it. And a test scans the source code for image-writing
> calls and fails the build if it finds one.

**"What accuracy does the counter achieve?"**
> Be honest and specific: on our prototype, clean single-file entry counts
> reliably; dense crowding at a narrow door is where it degrades, which is why
> production uses an overhead angle and head detection. Quote a measured number
> if you have one by then — don't invent one.

**"Why Qualcomm hardware?"**
> 12 TOPS on-device is what makes the privacy claim possible at all — if we
> needed cloud GPUs, the video would have to leave the store. The NPU is what
> turns the principle into an architecture.

**"What if the shop has no CCTV?"**
> Then it's two low-cost cameras and the same box. Reusing existing CCTV lowers
> the cost of adoption, it isn't a dependency.

**"Is the stock data real?"**
> In the prototype it's simulated, and we label it as simulated in the UI.
> Production reads it from the billing software via the POS integrations.

---

## 3-minute cut

If you're cut short, present only these:

1. **Slide 2** — the problem in one sentence, the Zero-Frame idea, the four
   modules by name (30s each max).
2. **Slide 3** — trace the flow diagram and say "the schema gate is enforced in
   code, not policy."
3. **Slide 5** — the four numbers and the never-do list.
4. Close on the comparison table line from slide 6.

Drop feasibility and references entirely; offer them as "happy to go deeper on
feasibility if useful."

---

## Delivery notes

- **Don't read the slides.** They're dense by SIH template requirement; your job
  is the narrative between them.
- The **strongest 20 seconds** in this deck is the never-do list on slide 5.
  Slow down there and make eye contact.
- If you get one demo moment, make it the **privacy page rejecting the fake
  image event** — it's the claim judges are most sceptical of and the one you
  can prove on the spot.
- Keep "prototype today" and "production target" in separate sentences, always.
