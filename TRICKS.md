# Tricks log

Informal running list of techniques/decisions used in this project worth
being able to talk about later. Not a design doc — just "oh right, here's
why I did that" notes, newest first.

## Trigram (`pg_trgm`) index for substring search

**Problem:** search does `name ILIKE '%dragon%'` — a leading wildcard, so a
normal B-tree index can't help (nothing to seek a prefix on). Postgres was
falling back to a full table scan + regex check on every row.

**Trick:** `pg_trgm` extension breaks every string into overlapping 3-char
chunks ("dragon" → dra/rag/ago/gon) and builds a GIN index over those
chunks. A `%dragon%` query gets broken into the same trigrams, looked up in
the index to find candidate rows, then double-checked with the real
`ILIKE` only on that shortlist — instead of every row in the table.

Applied to `cards.name` / `oracle_text` / `type_line`. Confirmed via
`EXPLAIN`: planner switched from a sequential scan to a bitmap index scan.

## HNSW index for vector similarity search

**Problem:** card embeddings (768-dim, via `pgvector`) power "find similar
cards" — nearest-neighbor search over 50k+ vectors. Brute-force distance
comparison against every row doesn't scale.

**Trick:** HNSW (Hierarchical Navigable Small World) is an approximate
nearest-neighbor index — builds a multi-layer graph so search hops toward
the nearest vectors instead of checking all of them. Trades a small amount
of recall for a big speedup. `pgvector` ships it as an index type
(`USING hnsw (embedding vector_cosine_ops)`), so it's just a `CREATE INDEX`,
no separate vector DB needed.

## Keyset (cursor) pagination instead of `OFFSET`

**Problem:** infinite-scroll feed. `OFFSET N LIMIT 30` gets slower as N
grows (Postgres still has to walk and discard the first N rows), and is
prone to skipped/duplicated rows if data changes between pages.

**Trick:** cursor = the last row's sort key from the previous page. Next
page is just `WHERE sort_key > $cursor ORDER BY sort_key LIMIT 30` — an
index seek, not a scan-and-discard, and stable regardless of how many pages
deep you are.

## Seeded per-request shuffle, still keyset-paginatable

**Problem:** wanted the browse feed to feel shuffled, not a static `ORDER
BY id` — but a real `ORDER BY random()` breaks keyset pagination (the order
isn't reproducible page to page, so you get dupes/gaps).

**Trick:** order by `md5(id || seed)` instead of `random()`. Same `id`
+ same `seed` always produces the same sort key, so it's a stable order
you can still keyset-paginate through — but a fresh `seed` each page load
gives a different-feeling shuffle. The cursor stays just "last row's id";
the server recomputes the hash for that id using the seed sent alongside
it. Left as the intended plug point for a future recommendation score —
swap the hash for a ranking score and the pagination mechanics don't move.

## Deterministic per-id hash instead of `Math.random()` (client-side)

**Same trick, client side:** picking which cards get a "wide" masonry tile
used `hash(card_id) % N` instead of a random roll on each render. Same card
always gets the same wide/normal verdict, so it doesn't flicker between
renders/refetches. (This particular feature got reverted — see below — but
the hashing trick itself is reusable.)

## Grounding a content filter in the data source's own fields, not guesses

**Problem:** wanted to hide "off-vibe" cards (memes, joke sets, crossover
promos) from the default feed, without hand-rolling a name/set blocklist
that'd need constant maintenance.

**Trick:** checked what Scryfall's bulk data already tags cards with
before writing any filter logic — `set_type == "funny"` already covers
joke/playtest sets as one field, and `promo_types` containing
`"universesbeyond"` already covers all crossover sets (Marvel, LOTR, Final
Fantasy, etc). Verified against real API responses via `curl` first. Zero
maintenance filter, because it rides on classification the data source
already maintains for its own reasons.

## In-process cache for Gemini NL→query translation

**Problem:** every natural-language search paid a Gemini round-trip, even
for exact repeat searches (retyping, or different users searching the same
popular phrase).

**Trick:** the translation step (NL text → structured query grammar) is a
pure-ish function — same input text, same output, basically every time. So
`nl_search.py` keeps a module-level dict cache keyed on the normalized
(trimmed, lowercased) input text; a cache hit skips Gemini entirely and
goes straight to parsing. Exact-string match only — paraphrases ("cheap
draw" vs "inexpensive card draw") still miss and re-hit Gemini, but that's
a fine tradeoff for how cheap this was to add.

## Masonry gap bug → bin-packing vs. greedy layout

**Problem:** wide (multi-column) tiles in a Pinterest-style masonry grid
left visible gaps.

**Root cause:** `masonry-layout` (the library) does *greedy* column-height
tracking — placing a 2-wide item just snaps both columns to whichever was
taller, and never backfills a gap left in the shorter one. It's not real
bin-packing, just a running per-column height counter.

**Trick that helped:** `packery` (same author, shares the same base
library — so it was a same-API drop-in) does real bin-packing — it
actually looks for a gap the item fits in before placing it.

**Trick that didn't fully solve it:** swapping the layout engine reduces
gaps but can't eliminate them purely from the outside — knowing "will this
placement leave a gap" needs visibility into the layout engine's internal
column state at insert time, which isn't something you can compute from
just a per-card hash before Packery ever runs. Wide tiles are on hold until
there's a real signal (recommendation match score) to justify placing one,
computed with the actual column state, not a blind hash.
