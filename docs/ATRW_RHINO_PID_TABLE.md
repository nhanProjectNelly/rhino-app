# Rhino ATRW pid table (same ordering as `prepare_atrw_from_rhino`)

Alphabetical order over **all** identity folder names → global pid `0 … 18`.

| pid | Identity        | Split |
|-----|-----------------|-------|
| 0   | Boma ID5301     | train |
| 1   | Bunji ID5030    | train |
| 2   | Donny ID1444    | test  |
| 3   | Ennex ID5220    | test  |
| 4   | Evan ID1044     | test  |
| 5   | Fanana ID6065   | train |
| 6   | Galla ID2221    | train |
| 7   | Goat ID1486     | test  |
| 8   | Gordon ID1076   | test  |
| 9   | Hannah ID6057   | train |
| 10  | Inkosi ID1484   | train |
| 11  | Ivory ID2289    | train |
| 12  | Lucky ID1279    | train |
| 13  | Mandi ID6182    | train |
| 14  | Nkazana ID2416  | train |
| 15  | Pikinini ID1068 | train |
| 16  | Senzeni ID6185  | train |
| 17  | Thabani ID6174  | train |
| 18  | Tsakani ID6087  | train |

- **Train (14 ids):** 0, 1, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18  
- **Test (5 ids, query + gallery only):** 2, 3, 4, 7, 8  

Train ∩ test = ∅.

Expected under `rhino_atrw_format/`:

- `train` jpgs: pids 0, 1, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18  
- `query` jpgs: pids 2, 3, 4, 7, 8  
- `gallery` jpgs: pids 2, 3, 4, 7, 8 (source split)

**App default (`sync_reid_test_data.py`):** After copy, **every pid 0–18** is ensured in `uploads/reid_atrw/gallery/` by copying one train image per missing pid (`*_reid_full_gallery.jpg`), so Re-ID retrieval is over the full identity set. Use `--no-full-gallery` to keep only the 5-pid gallery. Existing tree: `--ensure-full-gallery-only`.
