# Event contract

Every event emitted by any StoreSmart module must be one of the shapes below,
enforced by `storesmart/common/events.py` (`EventGate`, pydantic models with
`extra="forbid"`, max 1 KB serialized). Modules call `EventBus.emit(dict)` —
never write to the database directly — so nothing bypasses the gate.

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

## Fields

| Field | Type | Notes |
|---|---|---|
| `t` | string | ISO-8601 timestamp, added automatically by `EventBus.emit` if missing |
| `cam` | string | camera role (`entrance`, `counter`, `floor`, `shelf`); omitted for store-wide events (`alert`, `summary`) |
| `type` | string | one of the 9 whitelisted types above |
| `track` | int | ephemeral, per-camera track ID — never persisted beyond the live view, never joined across cameras |

## Adding a new event type

1. Add a new pydantic model to `storesmart/common/events.py` with
   `model_config = ConfigDict(extra="forbid")`.
2. Register it in `EVENT_TYPES`.
3. Add a test in `tests/test_event_gate.py` proving both a valid instance is
   accepted and an event with an unexpected field is rejected.

Never widen an existing model with extra fields instead of adding a new type
— that's how an image blob would sneak past the gate.

## Retention

`position` events are pruned by `EventBus` once older than
`privacy.position_retention_s` (default 300s, see `config/settings.yaml`) —
they only ever feed the live map, not long-term analytics. Dwell/heatmap
aggregates are computed from `dwell` events instead, which don't carry raw
coordinates.
