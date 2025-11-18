# History marker contract

The history layer stores structured output items in OpenWebUI's chat store and
emits hidden markers inside assistant messages so those items can be recovered
later. The contract is intentionally small and structural—no behavioural changes
are expected when refactoring this layer.

- **Persistence boundary**: `HistoryPersistence.store_items` cleans output item
  payloads (drops upstream `id` fields) and delegates to a minimal
  `HistoryRepository` wrapper over `ItemStore`. Storage and marker rendering are
  separate so persistence can be exercised without mutating streaming buffers.
- **Marker rendering**: `HistoryPersistence.render_hidden_markers` wraps marker
  metadata (`type`, ULID, `model_id`) for each stored payload. Emission happens
  after storage so tests can assert on the marker text independently.
- **Marker resolution**: `collect_marker_item_ids` finds referenced ULIDs in
  assistant messages; `resolve_marker_payloads` uses a resolver that closes over
  chat/model metadata to fetch stored payloads. `HistoryBuilder` then focuses on
  shaping roles and text into Responses-style items.
- **Instruction extraction**: `extract_system_instructions` is the shared helper
  for both history reconstruction and request building, keeping instruction
  handling consistent across the manifold.
