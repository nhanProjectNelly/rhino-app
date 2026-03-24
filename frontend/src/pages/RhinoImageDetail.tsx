import { useParams, Link } from 'react-router-dom';
import { useState, useEffect, useCallback } from 'react';
import { gallery as galleryApi } from '../api';
import { ImageCropper } from '../components/ImageCropper';
import {
  MANUAL_OPTIONS,
  buildManualPartsWithNotes,
  parseDescriptionPartsToForm,
} from '../constants/manualOptions';
import { DESCRIPTION_PART_LABELS } from '../constants/descriptionExample';

const API_BASE = '';

function EyeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

type Slot = {
  id: number;
  url: string;
  parent_url: string;
  is_anchor_fallback?: boolean;
};

type CaptureDetail = {
  identity_id: number;
  identity_name: string;
  anchor_image_id: number;
  source_stem: string | null;
  anchor: { id: number; url: string };
  slots: Record<string, Slot | null | undefined>;
  canonical_description_parts: Record<string, string> | null;
  four_parts_key_default: string;
};

type PartKey = 'left_ear' | 'right_ear' | 'head' | 'body';
const PART_ORDER: PartKey[] = ['left_ear', 'right_ear', 'head', 'body'];

type CropModal =
  | null
  | { mode: 'create'; partKey: PartKey; parentUrl: string }
  | { mode: 'replace'; partKey: PartKey; imageId: number; parentUrl: string };

const emptyNotes: Record<PartKey, string> = {
  left_ear: '',
  right_ear: '',
  head: '',
  body: '',
};

export function RhinoImageDetail() {
  const { identityId, imageId } = useParams<{ identityId: string; imageId: string }>();
  const iid = Number(identityId);
  const imgId = Number(imageId);
  const [detail, setDetail] = useState<CaptureDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [descForm, setDescForm] = useState<Record<string, Record<string, string>>>({
    left_ear: {},
    right_ear: {},
    head: {},
    body: {},
  });
  const [descNotes, setDescNotes] = useState<Record<PartKey, string>>({ ...emptyNotes });
  const [saving, setSaving] = useState(false);
  const [regenLoading, setRegenLoading] = useState(false);
  const [cropModal, setCropModal] = useState<CropModal>(null);
  const [cropSaving, setCropSaving] = useState(false);

  const applyLoadedDescription = useCallback((c: Record<string, string> | null) => {
    const { form, partNotes } = parseDescriptionPartsToForm(c);
    setDescForm(form);
    setDescNotes({ ...emptyNotes, ...partNotes });
  }, []);

  const load = useCallback(() => {
    if (!Number.isFinite(iid) || !Number.isFinite(imgId)) {
      setErr('Invalid URL');
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    galleryApi
      .getCaptureDetail(iid, imgId)
      .then((r) => {
        setDetail(r.data);
        applyLoadedDescription(r.data.canonical_description_parts);
      })
      .catch((e) => {
        setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to load');
        setDetail(null);
      })
      .finally(() => setLoading(false));
  }, [iid, imgId, applyLoadedDescription]);

  useEffect(() => {
    load();
  }, [load]);

  const builtParts = () => buildManualPartsWithNotes(descForm, descNotes);

  const saveDescription = async () => {
    if (!detail) return;
    const p = builtParts();
    setSaving(true);
    try {
      await galleryApi.saveManualDescription(detail.anchor_image_id, p);
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const regenerateWithLlm = async () => {
    if (!detail) return;
    const s = detail.slots;
    const p = builtParts();
    setRegenLoading(true);
    setErr(null);
    try {
      const res = await galleryApi.describe(
        iid,
        String(detail.source_stem ?? detail.anchor_image_id),
        {
          left_ear_id: s.left_ear?.id,
          right_ear_id: s.right_ear?.id,
          head_id: s.head?.id,
          body_id: s.body?.id,
        },
        {
          left_ear_text: p.left_ear || undefined,
          right_ear_text: p.right_ear || undefined,
          head_text: p.head || undefined,
          body_text: p.body || undefined,
          four_parts_key: detail.four_parts_key_default,
          llm_regenerate_with_form_hints: true,
          anchor_image_id: detail.anchor_image_id,
        }
      );
      applyLoadedDescription(res.data.part_texts ?? null);
      await load();
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (e as Error)?.message ||
        'Regenerate failed';
      setErr(String(msg));
    } finally {
      setRegenLoading(false);
    }
  };

  const onCropComplete = async (file: File) => {
    if (!detail || !cropModal) return;
    setCropSaving(true);
    try {
      if (cropModal.mode === 'create') {
        await galleryApi.partCropFromParent(iid, detail.anchor_image_id, cropModal.partKey, file);
      } else {
        await galleryApi.updateImage(cropModal.imageId, file);
      }
      setCropModal(null);
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      setCropSaving(false);
    }
  };

  const openPartCrop = (key: PartKey) => {
    if (!detail) return;
    const slot = detail.slots[key] as Slot | null | undefined;
    const originUrl = detail.anchor.url;
    if (!slot) {
      setCropModal({ mode: 'create', partKey: key, parentUrl: originUrl });
      return;
    }
    if (slot.is_anchor_fallback && key === 'body') {
      setCropModal({ mode: 'create', partKey: 'body', parentUrl: originUrl });
      return;
    }
    setCropModal({
      mode: 'replace',
      partKey: key,
      imageId: slot.id,
      parentUrl: slot.parent_url,
    });
  };

  if (loading && !detail) {
    return (
      <div className="page rhino-img-detail">
        <p className="loading">Loading…</p>
      </div>
    );
  }

  if (err && !detail) {
    return (
      <div className="page rhino-img-detail">
        <p className="error">{err}</p>
        <Link to="/lists">Back to rhino list</Link>
      </div>
    );
  }

  if (!detail) return null;

  const cropModalTitle =
    cropModal?.mode === 'create'
      ? `Crop from origin: ${DESCRIPTION_PART_LABELS[cropModal.partKey]}`
      : cropModal
        ? `Re-crop: ${DESCRIPTION_PART_LABELS[cropModal.partKey]}`
        : '';

  return (
    <div className="page rhino-img-detail">
      <div className="rhino-img-detail-header">
        <Link to="/lists" className="back-link">
          ← Rhino list
        </Link>
        <h1>
          {detail.identity_name}
          <span className="rhino-img-detail-sub">
            {' '}
            · Capture {detail.source_stem ?? `#${detail.anchor_image_id}`}
          </span>
        </h1>
        <p className="section-note hint">
          Part crops (left) and description ticks (right). Eye on image = crop from origin or re-crop.
        </p>
      </div>

      {err && <p className="error">{err}</p>}

      <section className="detail-section-parts">
        <div className="detail-part-rows">
          {PART_ORDER.map((key) => {
            const slot = detail.slots[key] as Slot | null | undefined;

            return (
              <div key={key} className="detail-part-row">
                <div className="detail-part-row-label">{DESCRIPTION_PART_LABELS[key]}</div>
                <div className="detail-part-row-body">
                  <div className="detail-part-thumb-wrap">
                    {!slot ? (
                      <button
                        type="button"
                        className="detail-part-thumb detail-part-thumb-empty"
                        onClick={() => openPartCrop(key)}
                        aria-label={`Add ${key} crop from origin`}
                      >
                        <span className="detail-part-thumb-placeholder">No crop</span>
                        <span className="detail-thumb-edit detail-thumb-edit-center" aria-hidden>
                          <EyeIcon />
                        </span>
                      </button>
                    ) : (
                      <div className="detail-part-thumb">
                        <img src={API_BASE + slot.url} alt="" />
                        <button
                          type="button"
                          className="detail-thumb-edit"
                          title={
                            slot.is_anchor_fallback && key === 'body'
                              ? 'Crop body from origin'
                              : 'Re-crop from parent'
                          }
                          aria-label={`View or edit ${key} crop`}
                          onClick={() => openPartCrop(key)}
                        >
                          <EyeIcon />
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="detail-part-form-col">
                    <div className="detail-manual-selects detail-manual-selects-row">
                      {Object.entries(MANUAL_OPTIONS[key]).map(([optKey, options]) => (
                        <span key={optKey} className="detail-manual-select-wrap">
                          <label>{optKey}</label>
                          <select
                            value={descForm[key]?.[optKey] ?? ''}
                            onChange={(e) =>
                              setDescForm((f) => ({
                                ...f,
                                [key]: { ...(f[key] || {}), [optKey]: e.target.value },
                              }))
                            }
                          >
                            {(options as string[]).map((v: string) => (
                              <option key={v || '—'} value={v}>
                                {v || `— ${optKey} —`}
                              </option>
                            ))}
                          </select>
                        </span>
                      ))}
                    </div>
                    <label className="detail-part-note-label">
                      Note (this part)
                      <textarea
                        rows={2}
                        className="detail-part-note"
                        placeholder="Optional"
                        value={descNotes[key]}
                        onChange={(e) => setDescNotes((n) => ({ ...n, [key]: e.target.value }))}
                      />
                    </label>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="detail-step-footer-spread" style={{ borderTop: 'none', marginTop: '1rem' }}>
          <div />
          <div className="rhino-img-detail-actions">
            <button type="button" onClick={saveDescription} disabled={saving}>
              {saving ? 'Saving…' : 'Save description'}
            </button>
            <button type="button" className="btn-primary" onClick={regenerateWithLlm} disabled={regenLoading}>
              {regenLoading ? 'Calling LLM…' : 'Regenerate with LLM'}
            </button>
          </div>
        </div>
      </section>

      {cropModal && (
        <div className="modal-overlay" onClick={() => !cropSaving && setCropModal(null)}>
          <div className="modal-content edit-reid-modal recrop-modal" onClick={(e) => e.stopPropagation()}>
            <h3>{cropModalTitle}</h3>
            <ImageCropper
              src={API_BASE + cropModal.parentUrl}
              commitMode="manual"
              onCancel={() => !cropSaving && setCropModal(null)}
              showCroppedPreview
              onCropComplete={onCropComplete}
            />
            {cropSaving && <p className="hint">Saving…</p>}
          </div>
        </div>
      )}
    </div>
  );
}
