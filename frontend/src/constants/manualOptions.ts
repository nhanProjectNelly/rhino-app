/** Tick options for manual description (by IndivAID part). */
export const MANUAL_OPTIONS = {
  left_ear: {
    edge: ['', 'intact', 'torn'],
    notches: ['', '0', '1', '2', '3+'],
    position: ['', 'top', 'mid', 'bottom', 'mixed', 'center'],
    /** Round / ID hole in ear center (Hussek-style: left ear → code position 10). */
    central_hole: ['', 'none', 'round_middle', 'irregular', 'unknown'],
    tuft: ['', 'present', 'absent'],
  },
  right_ear: {
    edge: ['', 'intact', 'torn'],
    notches: ['', '0', '1', '2', '3+'],
    position: ['', 'top', 'mid', 'bottom', 'mixed', 'center'],
    central_hole: ['', 'none', 'round_middle', 'irregular', 'unknown'],
    tuft: ['', 'present', 'absent'],
  },
  head: {
    viewpoint: ['', 'front', 'front_left', 'front_right', 'side_left', 'side_right', 'rear'],
    horn: ['', 'short blunt', 'short sharp', 'medium blunt', 'medium sharp', 'long blunt', 'long sharp', 'curved', 'straight'],
    muzzle: ['', 'round', 'elongated'],
    wrinkles: ['', 'low', 'medium', 'high'],
  },
  body: {
    skin: ['', 'smooth', 'moderate_wrinkle', 'heavy_wrinkle'],
    size: ['', 'small', 'medium', 'large'],
    viewpoint: ['', 'full', 'partial'],
  },
} as const;

export type EarTearRow = {
  notches: string;
  position: string;
  central_hole: string;
  note: string;
};

const emptyTear = (): EarTearRow => ({
  notches: '',
  position: '',
  central_hole: '',
  note: '',
});

/** Serialize one ear: intact, or torn + list of tears (each = one damaged area). */
export function buildEarPartString(tuft: string, tears: EarTearRow[]): string {
  const t = (tuft || '').trim();
  const rows = tears.filter((r) => r.notches || r.position || r.central_hole || r.note.trim());
  if (rows.length === 0) {
    const parts = ['edge intact'];
    if (t) parts.push(`tuft ${t}`);
    return parts.join('; ');
  }
  const parts: string[] = ['edge torn'];
  for (const r of rows) {
    const note = r.note.trim().replace(/;/g, ',');
    parts.push(
      `tear notches ${r.notches || '0'} position ${r.position || 'unknown'} central_hole ${r.central_hole || 'unknown'}${
        note ? ` note ${note}` : ''
      }`
    );
  }
  if (t) parts.push(`tuft ${t}`);
  return parts.join('; ');
}

function buildPartString(part: keyof typeof MANUAL_OPTIONS, values: Record<string, string>): string {
  const opts = MANUAL_OPTIONS[part];
  const parts: string[] = [];
  for (const [key] of Object.entries(opts)) {
    const v = values[key];
    if (v && v !== '') parts.push(`${key} ${v}`);
  }
  return parts.join('; ') || '';
}

function earStringFromForm(
  flat: Record<string, string>,
  tearsFromUi: EarTearRow[] | undefined
): string {
  const tuft = flat.tuft || '';
  const filled = (tearsFromUi || []).filter((r) => r.notches || r.position || r.central_hole || r.note.trim());
  if (filled.length > 0) return buildEarPartString(tuft, filled);
  if (flat.edge === 'intact' || flat.edge === '') return buildEarPartString(tuft, []);
  if (flat.notches || flat.position || flat.central_hole) {
    return buildEarPartString(tuft, [
      {
        notches: flat.notches || '0',
        position: flat.position || 'unknown',
        central_hole: flat.central_hole || 'unknown',
        note: '',
      },
    ]);
  }
  return buildEarPartString(tuft, []);
}

export function buildManualParts(
  form: Record<string, Record<string, string>>,
  earTears?: { left_ear?: EarTearRow[]; right_ear?: EarTearRow[] }
): { left_ear: string; right_ear: string; head: string; body: string } {
  return {
    left_ear: earStringFromForm(form.left_ear || {}, earTears?.left_ear),
    right_ear: earStringFromForm(form.right_ear || {}, earTears?.right_ear),
    head: buildPartString('head', form.head || {}),
    body: buildPartString('body', form.body || {}),
  };
}

const PART_KEYS = ['left_ear', 'right_ear', 'head', 'body'] as const;

/** Parse stored description_parts: ear tears + flat fields. */
export function parseEarPartString(s: string): { tuft: string; tears: EarTearRow[]; edgeIntact: boolean } {
  const tears: EarTearRow[] = [];
  let tuft = '';
  let edgeIntact = true;
  const segments = s.split(';').map((t) => t.trim()).filter(Boolean);
  let legacy: Partial<EarTearRow> = {};
  for (const seg of segments) {
    if (seg.startsWith('tear ')) {
      const rest = seg.slice(5).trim();
      const m = /^notches (\S+) position (\S+) central_hole (\S+)(?: note (.+))?$/.exec(rest);
      if (m) {
        tears.push({
          notches: m[1],
          position: m[2],
          central_hole: m[3],
          note: (m[4] || '').trim(),
        });
      }
    } else if (seg.startsWith('edge ')) {
      const e = seg.slice(5).trim();
      if (e === 'torn' || e === 'ragged') edgeIntact = false;
      if (e === 'intact') edgeIntact = true;
    } else if (seg.startsWith('tuft ')) tuft = seg.slice(5).trim();
    else if (seg.startsWith('notches ')) legacy.notches = seg.slice(8).trim();
    else if (seg.startsWith('position ')) legacy.position = seg.slice(9).trim();
    else if (seg.startsWith('central_hole ')) legacy.central_hole = seg.slice(13).trim();
  }
  if (tears.length === 0 && (legacy.notches || legacy.position || legacy.central_hole)) {
    tears.push({
      notches: legacy.notches || '0',
      position: legacy.position || 'unknown',
      central_hole: legacy.central_hole || 'unknown',
      note: '',
    });
    edgeIntact = false;
  }
  if (tears.length > 0) edgeIntact = false;
  return { tuft, tears: tears.length ? tears : [], edgeIntact };
}

export function parseDescriptionPartsToForm(description_parts: Record<string, string> | null): {
  form: Record<string, Record<string, string>>;
  note: string;
  partNotes: Record<(typeof PART_KEYS)[number], string>;
  earTears: { left_ear: EarTearRow[]; right_ear: EarTearRow[] };
} {
  const form: Record<string, Record<string, string>> = { left_ear: {}, right_ear: {}, head: {}, body: {} };
  const partNotes: Record<(typeof PART_KEYS)[number], string> = {
    left_ear: '',
    right_ear: '',
    head: '',
    body: '',
  };
  const earTears = { left_ear: [] as EarTearRow[], right_ear: [] as EarTearRow[] };
  if (!description_parts) {
    return { form, note: '', partNotes, earTears };
  }
  for (const part of PART_KEYS) {
    let s = description_parts[part];
    if (!s || typeof s !== 'string') continue;
    const match = s.match(/\s+note:\s+(.*)$/);
    if (match) {
      partNotes[part] = match[1].trim();
      s = s.replace(/\s+note:\s+.*$/, '').trim();
    }
    if (part === 'left_ear' || part === 'right_ear') {
      const { tuft, tears, edgeIntact } = parseEarPartString(s);
      form[part].tuft = tuft;
      form[part].edge = edgeIntact ? 'intact' : 'torn';
      earTears[part] = tears.length ? tears : edgeIntact ? [] : [{ ...emptyTear() }];
      continue;
    }
    const segments = s.split(';').map((t) => t.trim()).filter(Boolean);
    for (const seg of segments) {
      const idx = seg.indexOf(' ');
      const key = idx >= 0 ? seg.slice(0, idx).trim() : seg;
      const value = idx >= 0 ? seg.slice(idx + 1).trim() : '';
      if (key && key in MANUAL_OPTIONS[part]) form[part][key] = value;
    }
  }
  return { form, note: partNotes.body, partNotes, earTears };
}

/** Build part strings from form and optional notes (e.g. for upload/edit modal). */
export function buildManualPartsWithNotes(
  form: Record<string, Record<string, string>>,
  notes: Record<string, string> = {},
  earTears?: { left_ear?: EarTearRow[]; right_ear?: EarTearRow[] }
): { left_ear: string; right_ear: string; head: string; body: string } {
  const parts = buildManualParts(form, earTears);
  (['left_ear', 'right_ear', 'head', 'body'] as const).forEach((part) => {
    const note = (notes[part] || '').trim();
    if (note) parts[part] = (parts[part] ? parts[part] + ' ' : '') + 'note: ' + note;
  });
  return parts;
}

/**
 * Strings to send as LLM form hints: skip default-only ear ("edge intact"), skip empty head/body.
 */
export function manualPartsForLlmHints(parts: {
  left_ear: string;
  right_ear: string;
  head: string;
  body: string;
}): Partial<Record<'left_ear' | 'right_ear' | 'head' | 'body', string>> {
  const o: Partial<Record<'left_ear' | 'right_ear' | 'head' | 'body', string>> = {};
  const le = parts.left_ear.trim();
  if (le && le !== 'edge intact') o.left_ear = le;
  const re = parts.right_ear.trim();
  if (re && re !== 'edge intact') o.right_ear = re;
  const h = parts.head.trim();
  if (h) o.head = h;
  const b = parts.body.trim();
  if (b) o.body = b;
  return o;
}

export { emptyTear };
