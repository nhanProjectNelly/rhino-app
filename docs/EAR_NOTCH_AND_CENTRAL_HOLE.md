# Rhino ear notch UI (central round hole)

## Previous gap

The form had **edge**, **notches**, **position** (rim), and **tuft** only. It did **not** explicitly encode a **round hole in the middle of the ear** (common in ear-notch ID systems).

## UI fields added

| Field | Meaning |
|-------|---------|
| **position** | Now includes **`center`** when the main mark is on the ear center / disc (not only rim top/mid/bottom). |
| **central_hole** | **`none`** — no central perforation. **`round_middle`** — clear round hole in the ear center (typical ID punch). **`irregular`** — damaged / non-round center opening. **`unknown`**. |

Stored text example: `central_hole round_middle`.

## Reference (Hussek-style coding, IndivAID prompts)

From `IndivAID/tools/generate_part_descriptions_llava.py` / Hussek prompts:

- **Right ear**: rim notch positions **1–5**; **central hole** → coded as position **5** on the right ear.
- **Left ear**: rim positions **6–10**; **central hole** → position **10** on the left ear.

Namibia-style prompts use separate **`has_central_hole`** and **`hole_value`** (e.g. 100/200). The app uses a single free-text pipeline; **`central_hole round_middle`** aligns with “ID hole in center” for training text.

## LLM part prompts

Per-ear vision prompts in `backend/app/services/describe.py` now mention central round holes so hybrid describe can surface them in `raw` text even when the user leaves manual fields empty.
