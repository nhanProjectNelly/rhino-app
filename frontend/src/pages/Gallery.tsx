import { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { gallery as galleryApi, predict as predictApi, crop as cropClient } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { ImageCropper, type ImageCropperHandle } from '../components/ImageCropper';
import { DESCRIPTION_PART_LABELS, EXAMPLE_RHINO_DESCRIPTION } from '../constants/descriptionExample';
import {
  MANUAL_OPTIONS,
  buildManualPartsWithNotes,
  manualPartsForLlmHints,
  buildManualParts,
  parseDescriptionPartsToForm,
  emptyTear,
  type EarTearRow,
} from '../constants/manualOptions';

const API_BASE = '';

type PopupPartKey = 'left_ear' | 'right_ear' | 'head' | 'body';
const POPUP_PART_ORDER: PopupPartKey[] = ['left_ear', 'right_ear', 'head', 'body'];
const EMPTY_PART_NOTES: Record<PopupPartKey, string> = {
  left_ear: '',
  right_ear: '',
  head: '',
  body: '',
};

function EyeIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function naturalImageSize(file: File): Promise<{ w: number; h: number }> {
  return new Promise((resolve, reject) => {
    const u = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(u);
      resolve({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(u);
      reject(new Error('image'));
    };
    img.src = u;
  });
}

function defaultCenterRect(w: number, h: number) {
  const mw = Math.max(80, Math.round(Math.min(w, h) * 0.45));
  const mh = Math.max(80, Math.round(Math.min(w, h) * 0.45));
  return {
    x: Math.max(0, Math.round((w - mw) / 2)),
    y: Math.max(0, Math.round((h - mh) / 2)),
    width: Math.min(mw, w),
    height: Math.min(mh, h),
  };
}

function cropRectToDataUrl(
  file: File,
  rect: { x: number; y: number; width: number; height: number }
): Promise<string> {
  return new Promise((resolve, reject) => {
    const u = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      try {
        const c = document.createElement('canvas');
        c.width = Math.max(1, rect.width);
        c.height = Math.max(1, rect.height);
        const ctx = c.getContext('2d');
        if (!ctx) {
          URL.revokeObjectURL(u);
          reject(new Error('canvas'));
          return;
        }
        ctx.drawImage(img, rect.x, rect.y, rect.width, rect.height, 0, 0, rect.width, rect.height);
        URL.revokeObjectURL(u);
        resolve(c.toDataURL('image/jpeg', 0.9));
      } catch (e) {
        URL.revokeObjectURL(u);
        reject(e);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(u);
      reject(new Error('image'));
    };
    img.src = u;
  });
}

type TopItem = {
  rank: number;
  id: number;
  id_name?: string;
  score: number;
  representative_image?: string;
  finalize_method?: string;
};
type FinalizeInfo = {
  id: number;
  score: number;
  method?: string;
  mean_set_top1_id?: number;
  majority_id?: number;
  majority_votes?: number;
  per_image_conflict?: boolean;
};
type PerImageRow = {
  path: string;
  top1_id: number;
  top1_score: number;
  margin: number;
  upload_rel?: string;
};
type PredictResult = {
  prediction_id?: number;
  query_url?: string;
  query_urls?: string[];
  set_folder_rel?: string;
  top_k?: TopItem[];
  top1?: TopItem;
  finalize?: FinalizeInfo | null;
  per_image?: PerImageRow[];
  demo_not_in_gallery_url?: string;
  top1_identity_id?: number;
  error?: string;
  reid_debug?: {
    use_app_descriptions?: boolean;
    query_images?: number;
    description_list_len?: number;
    lengths_match?: boolean;
    hint?: string;
    gallery_encoding?: string;
    per_query?: Array<{
      index: number;
      encoding: string;
      chars: Record<string, number>;
    }>;
    pid_score_mode?: string;
  };
};
type PredictionHistoryRow = {
  id: number;
  query_url: string;
  top1_score: number | null;
  confirmed?: boolean;
  reported?: boolean;
  corrected_identity_id?: number | null;
};
type Identity = { id: number; name: string; pid: number | null; is_active?: boolean };
type Image = {
  id: number;
  identity_id: number;
  file_path: string;
  url: string;
  part_type: string | null;
  parent_image_id?: number | null;
  source_stem?: string | null;
  confirmed: boolean;
  is_active?: boolean;
  description_schema: unknown;
  description_parts: Record<string, string> | null;
  description_source: string | null;
  review_status?: 'draft' | 'pending_review' | 'junk' | 'confirmed';
  review_reason?: string | null;
};

type PendingItem = { id: string; file: File; preview: string };

type BatchItem = {
  id: string;
  file: File;
  preview: string;
  description: { description_schema: unknown; description_parts: Record<string, string> } | null;
};

function getImageFiles(files: FileList | null): File[] {
  if (!files) return [];
  return Array.from(files).filter((f) => f.type.startsWith('image/'));
}

function fileToPendingItem(file: File): PendingItem {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    file,
    preview: URL.createObjectURL(file),
  };
}

export function Gallery() {
  const location = useLocation();
  const { role } = useAuth();
  const isReID = location.pathname === '/';
  const pageTitle = isReID ? 'Re-identify rhino' : 'Rhino list';
  const isAdmin = role === 'admin';
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [images, setImages] = useState<Image[]>([]);
  const [imageFilter, setImageFilter] = useState<'all' | 'draft' | 'pending_review' | 'junk' | 'confirmed'>('all');
  const [selectedIdentityId, setSelectedIdentityId] = useState<number | null>(null);
  const [pendingFiles, setPendingFiles] = useState<PendingItem[]>([]);
  const [editPendingId, setEditPendingId] = useState<string | null>(null);
  const [editFile, setEditFile] = useState<File | null>(null);
  const [editCroppedFile, setEditCroppedFile] = useState<File | null>(null);
  const [editDescForm, setEditDescForm] = useState<Record<string, Record<string, string>>>({ left_ear: {}, right_ear: {}, head: {}, body: {} });
  const [editDescPartNotes, setEditDescPartNotes] = useState<Record<PopupPartKey, string>>({ ...EMPTY_PART_NOTES });
  const [step2PartPreviews, setStep2PartPreviews] = useState<Partial<Record<PopupPartKey, string>>>({});
  const [step2PartsLoading, setStep2PartsLoading] = useState(false);
  const [reidSaving, setReidSaving] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [jsonViewId, setJsonViewId] = useState<number | null>(null);
  const [manualForm, setManualForm] = useState<Record<number, Record<string, Record<string, string>>>>({});
  const [manualEarTears, setManualEarTears] = useState<
    Record<number, { left_ear: EarTearRow[]; right_ear: EarTearRow[] }>
  >({});
  const [editEarTears, setEditEarTears] = useState<{
    left_ear: EarTearRow[];
    right_ear: EarTearRow[];
  }>({ left_ear: [], right_ear: [] });
  const [o4LoadingId, setO4LoadingId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [newRhinoName, setNewRhinoName] = useState('');
  const [newRhinoPid, setNewRhinoPid] = useState<string>('');
  const [editingIdentityId, setEditingIdentityId] = useState<number | null>(null);
  const [editIdentityName, setEditIdentityName] = useState('');
  const [editIdentityPid, setEditIdentityPid] = useState<string>('');

  const [predictResult, setPredictResult] = useState<PredictResult | null>(null);
  const [predictLoading, setPredictLoading] = useState(false);
  const [reportPredictionId, setReportPredictionId] = useState<number | null>(null);
  const [reportCorrectIdentityId, setReportCorrectIdentityId] = useState<number | null>(null);
  const [reportSaving, setReportSaving] = useState(false);
  const [predictionHistory, setPredictionHistory] = useState<PredictionHistoryRow[]>([]);
  /** Admin: filter prediction history to reported rows only (API: reported_only). */
  const [historyReportedOnly, setHistoryReportedOnly] = useState(false);

  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [editBatchId, setEditBatchId] = useState<string | null>(null);
  const [describeSaving, setDescribeSaving] = useState(false);
  /** Re-ID + Add rhino popup: 1 = crop, 2 = describe. Edit existing = single screen. */
  const [editPopupStep, setEditPopupStep] = useState<1 | 2>(1);
  const [step1PixelRect, setStep1PixelRect] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const [step1BboxLoading, setStep1BboxLoading] = useState(false);
  /** After Next: restoring step 1 skips YOLO, uses this rect (manual adjust). */
  const [step1CommittedRect, setStep1CommittedRect] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const step1CropperRef = useRef<ImageCropperHandle>(null);
  const step2LoadedFkRef = useRef<string | null>(null);
  const [step2PartRects, setStep2PartRects] = useState<
    Partial<Record<PopupPartKey, { x: number; y: number; width: number; height: number }>>
  >({});
  const [step2ImageSize, setStep2ImageSize] = useState<{ w: number; h: number } | null>(null);
  const [partCropTarget, setPartCropTarget] = useState<PopupPartKey | null>(null);
  const [partCropInitialRect, setPartCropInitialRect] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const partCropperRef = useRef<ImageCropperHandle>(null);

  const IDENTITY_PAGE_SIZE = 20;
  const [identitySearchInput, setIdentitySearchInput] = useState('');
  const [identitySearchQ, setIdentitySearchQ] = useState('');
  const [identityListPage, setIdentityListPage] = useState(1);
  const [identityListTotal, setIdentityListTotal] = useState(0);
  const [identityListPages, setIdentityListPages] = useState(1);
  const [identitiesLoading, setIdentitiesLoading] = useState(false);
  const [identityListNonce, setIdentityListNonce] = useState(0);
  const [selectedIdentitySummary, setSelectedIdentitySummary] = useState<Identity | null>(null);
  const [reidIdentities, setReidIdentities] = useState<Identity[]>([]);
  const identitySearchPrevQ = useRef<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setIdentitySearchQ(identitySearchInput.trim()), 350);
    return () => clearTimeout(t);
  }, [identitySearchInput]);

  useEffect(() => {
    if (identitySearchPrevQ.current === null) {
      identitySearchPrevQ.current = identitySearchQ;
      return;
    }
    if (identitySearchPrevQ.current !== identitySearchQ) {
      identitySearchPrevQ.current = identitySearchQ;
      setIdentityListPage(1);
    }
  }, [identitySearchQ]);

  useEffect(() => {
    if (isReID) return;
    let cancelled = false;
    setIdentitiesLoading(true);
    galleryApi
      .getIdentities({
        page: identityListPage,
        page_size: IDENTITY_PAGE_SIZE,
        q: identitySearchQ || undefined,
      })
      .then((r) => {
        if (!cancelled) {
          setIdentities(r.data.items);
          setIdentityListTotal(r.data.total);
          setIdentityListPages(r.data.pages);
        }
      })
      .catch(() => {
        if (!cancelled) setIdentities([]);
      })
      .finally(() => {
        if (!cancelled) setIdentitiesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isReID, identityListPage, identitySearchQ, identityListNonce]);

  useEffect(() => {
    if (!isReID) return;
    galleryApi
      .getIdentities({ all: true })
      .then((r) => setReidIdentities(r.data.items))
      .catch(() => setReidIdentities([]));
  }, [isReID]);

  const PREDICTION_HISTORY_LIMIT = 10;
  const loadPredictionHistory = useCallback(
    () =>
      predictApi
        .history(
          PREDICTION_HISTORY_LIMIT,
          undefined,
          isAdmin && historyReportedOnly ? true : undefined
        )
        .then((r) => setPredictionHistory(r.data as PredictionHistoryRow[])),
    [isAdmin, historyReportedOnly]
  );

  useEffect(() => {
    if (!isReID) return;
    loadPredictionHistory().catch(() => setPredictionHistory([]));
  }, [isReID, loadPredictionHistory]);

  const refreshIdentityList = () => setIdentityListNonce((n) => n + 1);

  const filterToParams = (
    filter: 'all' | 'draft' | 'pending_review' | 'junk' | 'confirmed'
  ): { confirmed?: boolean; reviewStatus?: 'draft' | 'pending_review' | 'junk' | 'confirmed' } => {
    if (filter === 'draft') return { confirmed: false, reviewStatus: 'draft' };
    if (filter === 'pending_review') return { reviewStatus: 'pending_review' };
    if (filter === 'junk') return { reviewStatus: 'junk' };
    if (filter === 'confirmed') return { confirmed: true, reviewStatus: 'confirmed' };
    return {};
  };
  const loadImages = (
    identityId?: number,
    confirmed?: boolean,
    reviewStatus?: 'draft' | 'pending_review' | 'junk' | 'confirmed'
  ) => galleryApi.getImages(identityId, undefined, confirmed, reviewStatus).then((r) => setImages(r.data));
  const pendingRef = useRef<PendingItem[]>([]);
  pendingRef.current = pendingFiles;

  useEffect(() => {
    loadImages();
  }, []);
  useEffect(() => {
    if (selectedIdentityId == null) return;
    const { confirmed, reviewStatus } = filterToParams(imageFilter);
    loadImages(selectedIdentityId, confirmed, reviewStatus);
  }, [selectedIdentityId, imageFilter]);

  const expandedDescKey =
    expandedId != null
      ? JSON.stringify(images.find((i) => i.id === expandedId)?.description_parts ?? null)
      : '';
  useEffect(() => {
    if (expandedId == null) return;
    const img = images.find((i) => i.id === expandedId);
    if (!img) return;
    const p = parseDescriptionPartsToForm(img.description_parts);
    setManualForm((prev) => ({ ...prev, [img.id]: p.form }));
    setManualEarTears((prev) => ({
      ...prev,
      [img.id]: {
        left_ear: p.earTears.left_ear.length ? p.earTears.left_ear : [],
        right_ear: p.earTears.right_ear.length ? p.earTears.right_ear : [],
      },
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- expandedDescKey encodes description changes for the expanded row
  }, [expandedId, expandedDescKey]);

  useEffect(() => {
    if (editPendingId || editBatchId) {
      setEditPopupStep(1);
    }
  }, [editPendingId, editBatchId]);

  /** Step 1: YOLO once per upload; returning from step 2 reuses committed rect (no re-detect). */
  useEffect(() => {
    const twoStep = !!(editPendingId || editBatchId);
    if (!twoStep || editPopupStep !== 1 || !(editFile instanceof File)) {
      return;
    }
    if (step1CommittedRect) {
      setStep1PixelRect(step1CommittedRect);
      setStep1BboxLoading(false);
      return;
    }
    let cancelled = false;
    setStep1BboxLoading(true);
    cropClient
      .suggestBbox(editFile, 'body')
      .then((r) => {
        if (!cancelled) {
          setStep1PixelRect({
            x: r.data.x,
            y: r.data.y,
            width: r.data.width,
            height: r.data.height,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setStep1PixelRect(null);
      })
      .finally(() => {
        if (!cancelled) setStep1BboxLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [editPopupStep, editPendingId, editBatchId, editFile, step1CommittedRect]);

  /** Step 2: auto part crops once per file; step 1↔2 does not re-run YOLO. */
  useEffect(() => {
    const twoStep = !!(editPendingId || editBatchId);
    if (!twoStep || editPopupStep !== 2 || !(editFile instanceof File)) {
      return;
    }
    const fk = `${editFile.name}-${editFile.size}-${editFile.lastModified}`;
    if (step2LoadedFkRef.current === fk) {
      setStep2PartsLoading(false);
      return;
    }
    let cancelled = false;
    setStep2PartsLoading(true);
    cropClient
      .suggestPartBboxes(editFile)
      .then(async (res) => {
        if (cancelled) return;
        const pr = res.data.parts;
        setStep2ImageSize({ w: res.data.image_width, h: res.data.image_height });
        const rects: Partial<Record<PopupPartKey, { x: number; y: number; width: number; height: number }>> = {};
        const next: Partial<Record<PopupPartKey, string>> = {};
        for (const k of POPUP_PART_ORDER) {
          const r = pr[k];
          if (r && r.width > 0 && r.height > 0) {
            rects[k] = { x: r.x, y: r.y, width: r.width, height: r.height };
            try {
              next[k] = await cropRectToDataUrl(editFile, r);
            } catch {
              /* skip */
            }
          }
        }
        if (!cancelled) {
          setStep2PartRects(rects);
          setStep2PartPreviews(next);
          step2LoadedFkRef.current = fk;
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStep2PartPreviews({});
          setStep2PartRects({});
          step2LoadedFkRef.current = fk;
        }
      })
      .finally(() => {
        if (!cancelled) setStep2PartsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [editPopupStep, editPendingId, editBatchId, editFile]);

  const resetPopupCropState = useCallback(() => {
    setStep1CommittedRect(null);
    setStep1PixelRect(null);
    step2LoadedFkRef.current = null;
    setStep2PartRects({});
    setStep2PartPreviews({});
    setStep2ImageSize(null);
    setPartCropTarget(null);
    setPartCropInitialRect(null);
  }, []);

  const openPartManualCrop = useCallback(
    async (pk: PopupPartKey) => {
      if (!(editFile instanceof File)) return;
      let r = step2PartRects[pk];
      if (!r) {
        try {
          const dim = step2ImageSize ?? (await naturalImageSize(editFile));
          r = defaultCenterRect(dim.w, dim.h);
        } catch {
          r = { x: 50, y: 50, width: 320, height: 320 };
        }
      }
      setPartCropInitialRect(r);
      setPartCropTarget(pk);
    },
    [editFile, step2PartRects, step2ImageSize]
  );

  const applyPartManualCrop = useCallback(async () => {
    const pk = partCropTarget;
    if (!pk || !(editFile instanceof File)) return;
    const r = partCropperRef.current?.getStencilInImagePixels();
    if (!r) return;
    try {
      const url = await cropRectToDataUrl(editFile, r);
      setStep2PartRects((prev) => ({ ...prev, [pk]: r }));
      setStep2PartPreviews((prev) => ({ ...prev, [pk]: url }));
    } catch {
      /* ignore */
    }
    setPartCropTarget(null);
    setPartCropInitialRect(null);
  }, [partCropTarget, editFile]);

  const batchRef = useRef<BatchItem[]>([]);
  batchRef.current = batchItems;

  useEffect(() => {
    if (batchItems.length === 0) setSelectedBatchId(null);
    else if (!selectedBatchId || !batchItems.some((b) => b.id === selectedBatchId)) setSelectedBatchId(batchItems[0].id);
  }, [batchItems, selectedBatchId]);

  useEffect(() => {
    return () => { pendingRef.current.forEach((p) => URL.revokeObjectURL(p.preview)); };
  }, []);
  useEffect(() => {
    return () => { batchRef.current.forEach((b) => URL.revokeObjectURL(b.preview)); };
  }, []);

  const addFiles = useCallback(
    (files: File[]) => {
      const imageFiles = files.filter((f) => f.type.startsWith('image/'));
      if (imageFiles.length === 0) return;
      const newItems = imageFiles.map(fileToPendingItem);
      setPendingFiles((prev) => [...prev, ...newItems]);
      if (isReID && newItems.length > 0) {
        resetPopupCropState();
        const first = newItems[0];
        setEditPendingId(first.id);
        setEditFile(first.file);
        setEditCroppedFile(null);
        setEditDescForm({ left_ear: {}, right_ear: {}, head: {}, body: {} });
        setEditDescPartNotes({ ...EMPTY_PART_NOTES });
        setEditEarTears({ left_ear: [], right_ear: [] });
        setEditBatchId(null);
      }
      if (!isReID && newItems.length > 0 && selectedIdentityId != null) {
        resetPopupCropState();
        const first = newItems[0];
        setEditPendingId(first.id);
        setEditFile(first.file);
        setEditCroppedFile(null);
        setEditDescForm({ left_ear: {}, right_ear: {}, head: {}, body: {} });
        setEditDescPartNotes({ ...EMPTY_PART_NOTES });
        setEditEarTears({ left_ear: [], right_ear: [] });
      }
    },
    [isReID, selectedIdentityId, resetPopupCropState]
  );

  const removePending = (id: string) => {
    setPendingFiles((prev) => {
      const item = prev.find((p) => p.id === id);
      if (item) URL.revokeObjectURL(item.preview);
      return prev.filter((p) => p.id !== id);
    });
  };

  const startEditPending = (item: PendingItem) => {
    resetPopupCropState();
    setEditPendingId(item.id);
    setEditFile(item.file);
    setEditCroppedFile(null);
    setEditDescForm({ left_ear: {}, right_ear: {}, head: {}, body: {} });
    setEditDescPartNotes({ ...EMPTY_PART_NOTES });
    setEditEarTears({ left_ear: [], right_ear: [] });
  };

  const handleReIDSave = async () => {
    const id = selectedIdentityId ?? undefined;
    const file = editCroppedFile ?? editFile;
    if (!id || !file) return;
    setReidSaving(true);
    try {
      const parts = buildManualPartsWithNotes(editDescForm, editDescPartNotes, editEarTears);

      const hasManual = !!(parts.left_ear || parts.right_ear || parts.head || parts.body);

      await galleryApi.uploadWithDescription(id, file, {
        left_ear: parts.left_ear || undefined,
        right_ear: parts.right_ear || undefined,
        head: parts.head || undefined,
        body: parts.body || undefined,
        run_llm: !hasManual,
        confirmed: false,
      });
      if (editPendingId && editPendingId !== 'single-upload') {
        removePending(editPendingId);
      }
      setEditPendingId(null);
      setEditFile(null);
      setEditCroppedFile(null);
      const { confirmed, reviewStatus } = filterToParams(imageFilter);
      loadImages(id, confirmed, reviewStatus);
    } catch (err) {
      console.error(err);
    } finally {
      setReidSaving(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    addFiles(getImageFiles(e.dataTransfer.files));
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const files = getImageFiles(e.clipboardData.files);
    if (files.length) { e.preventDefault(); addFiles(files); }
  };

  const confirmImage = async (imageId: number) => {
    await galleryApi.confirmImage(imageId);
    loadImages(selectedIdentityId ?? undefined);
  };

  const deactivateImage = async (imageId: number) => {
    await galleryApi.deactivateImage(imageId);
    loadImages(selectedIdentityId ?? undefined);
  };

  const createRhino = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRhinoName.trim()) return;
    try {
      await galleryApi.createIdentity(newRhinoName.trim(), newRhinoPid ? parseInt(newRhinoPid, 10) : undefined);
      setNewRhinoName('');
      setNewRhinoPid('');
      refreshIdentityList();
    } catch (err) { console.error(err); }
  };

  const startEditIdentity = (i: Identity) => {
    setEditingIdentityId(i.id);
    setEditIdentityName(i.name);
    setEditIdentityPid(i.pid != null ? String(i.pid) : '');
  };

  const saveEditIdentity = async (e: React.FormEvent) => {
    e.preventDefault();
    if (editingIdentityId == null) return;
    try {
      await galleryApi.updateIdentity(editingIdentityId, {
        name: editIdentityName.trim(),
        pid: editIdentityPid ? parseInt(editIdentityPid, 10) : null,
      });
      setEditingIdentityId(null);
      refreshIdentityList();
      setSelectedIdentitySummary((prev) =>
        prev?.id === editingIdentityId
          ? {
              ...prev,
              name: editIdentityName.trim(),
              pid: editIdentityPid ? parseInt(editIdentityPid, 10) : null,
            }
          : prev
      );
    } catch (err) { console.error(err); }
  };

  const deactivateRhino = async (id: number) => {
    if (!window.confirm('Deactivate this rhino? (Soft delete, can be restored later)')) return;
    try {
      await galleryApi.deactivateIdentity(id);
      if (selectedIdentityId === id) {
        setSelectedIdentityId(null);
        setSelectedIdentitySummary(null);
      }
      refreshIdentityList();
    } catch (err) { console.error(err); }
  };

  const saveManual = async (img: Image) => {
    const form = manualForm[img.id] || {};
    const earT = manualEarTears[img.id];
    const parts = buildManualParts(form, earT);
    try {
      await galleryApi.saveManualDescription(img.id, parts);
      loadImages(selectedIdentityId ?? undefined);
    } catch (err) { console.error(err); }
  };

  const runO4mini = async (imageId: number) => {
    setO4LoadingId(imageId);
    try {
      await galleryApi.describeO4mini(imageId);
      loadImages(selectedIdentityId ?? undefined);
    } catch (err) { console.error(err); } finally { setO4LoadingId(null); }
  };

  const setManualOption = (imageId: number, part: string, key: string, value: string) => {
    setManualForm((prev) => ({
      ...prev,
      [imageId]: {
        ...(prev[imageId] || {}),
        [part]: { ...(prev[imageId]?.[part] || {}), [key]: value },
      },
    }));
  };

  const saveFromEditPopup = async () => {
    // Use cropped image when user cropped; only this file is sent (no original kept).
    const file = editCroppedFile ?? editFile;
    if (!file) return;
    setDescribeSaving(true);
    try {
      const built = buildManualPartsWithNotes(editDescForm, editDescPartNotes, editEarTears);
      const hints = manualPartsForLlmHints(built);
      const res = await predictApi.describeFile(file, hints);
      const description = res.data;
      const preview = URL.createObjectURL(file);
      if (editBatchId) {
        setBatchItems((prev) => {
          const old = prev.find((b) => b.id === editBatchId);
          if (old) URL.revokeObjectURL(old.preview);
          return prev.map((b) =>
            b.id === editBatchId ? { ...b, file, preview, description } : b
          );
        });
      } else {
        const id = `batch-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        setBatchItems((prev) => [...prev, { id, file, preview, description }]);
        if (editPendingId) {
          setPendingFiles((p) => {
            const item = p.find((x) => x.id === editPendingId);
            if (item) URL.revokeObjectURL(item.preview);
            return p.filter((x) => x.id !== editPendingId);
          });
        }
      }
      setEditPendingId(null);
      setEditFile(null);
      setEditCroppedFile(null);
      setEditBatchId(null);
    } catch (err) {
      console.error(err);
    } finally {
      setDescribeSaving(false);
    }
  };

  const removeBatchItem = (id: string) => {
    setBatchItems((prev) => {
      const item = prev.find((b) => b.id === id);
      if (item) URL.revokeObjectURL(item.preview);
      return prev.filter((b) => b.id !== id);
    });
  };

  const startEditBatchItem = (item: BatchItem) => {
    resetPopupCropState();
    setEditBatchId(item.id);
    setEditPendingId(null);
    setEditFile(item.file);
    setEditCroppedFile(null);
    const parts = item.description?.description_parts;
    if (parts) {
      const parsed = parseDescriptionPartsToForm(parts);
      setEditDescForm(parsed.form);
      setEditDescPartNotes(parsed.partNotes);
      setEditEarTears({
        left_ear: parsed.earTears.left_ear.length ? parsed.earTears.left_ear : [],
        right_ear: parsed.earTears.right_ear.length ? parsed.earTears.right_ear : [],
      });
    } else {
      setEditDescForm({ left_ear: {}, right_ear: {}, head: {}, body: {} });
      setEditDescPartNotes({ ...EMPTY_PART_NOTES });
      setEditEarTears({ left_ear: [], right_ear: [] });
    }
  };

  const runPredictSet = async () => {
    if (batchItems.length === 0) return;
    setPredictLoading(true);
    setPredictResult(null);
    try {
      const files = batchItems.map((b) => b.file);
      const descList = batchItems.map((b) => b.description?.description_parts ?? null);
      const res = await predictApi.uploadSet(files, descList);
      setPredictResult(res.data);
      if (import.meta.env.DEV && res.data?.reid_debug) {
        console.debug('[Re-ID]', res.data.reid_debug);
      }
      loadPredictionHistory().catch(() => {});
    } catch (err) {
      setPredictResult({ error: (err as Error).message });
    } finally {
      setPredictLoading(false);
    }
  };

  const selectedIdentity =
    selectedIdentityId == null
      ? undefined
      : selectedIdentitySummary?.id === selectedIdentityId
        ? selectedIdentitySummary
        : identities.find((i) => i.id === selectedIdentityId);
  const activeIdentities = (isReID ? reidIdentities : identities).filter((i) => i.is_active !== false);

  return (
    <div className="page gallery-page" onPaste={handlePaste}>
      <h1>{pageTitle}</h1>

      {isReID ? (
        <div className="reid-form">
          <section className="section section-upload-first">
            <h2>Upload image</h2>
            <p className="section-note">Upload one or more images. Edit popup opens to crop; Save runs o4-mini to generate description JSON and adds the image to the set below. Use Predict to run prediction on the whole set only.</p>
            <div
              className={`gallery-drop-zone ${dragOver ? 'drag-over' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              style={{ marginTop: '0.5rem' }}
            >
              <p>Select files to upload</p>
              <p className="hint">Or drag and drop, copy and paste files into this box.</p>
              <label className="btn-add-inline">
                Add image
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => { addFiles(getImageFiles(e.target.files)); e.target.value = ''; }}
                />
              </label>
            </div>
            {pendingFiles.length > 0 && (
              <ul className="gallery-pending-list sub-images">
                {pendingFiles.map((item) => (
                  <li key={item.id} className="gallery-pending-item">
                    <img src={item.preview} alt="" className="thumb" />
                    <span className="info">{item.file.name}</span>
                    <div className="actions">
                      <button type="button" className="btn-edit-small" onClick={() => startEditPending(item)}>Edit</button>
                      <button type="button" onClick={() => removePending(item.id)}>Delete</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="section section-form-like">
            <h2>Current upload set</h2>
            <p className="section-note">Select an image to view description; Edit to crop or change; Predict runs on the whole set.</p>
            {batchItems.length === 0 ? (
              <p className="hint">No images in set. Upload images and Save from the edit popup to add them here.</p>
            ) : (
              <div className="batch-set-layout">
                <div className="batch-set-main">
                  <div className="batch-set-preview">
                    {selectedBatchId && batchItems.find((b) => b.id === selectedBatchId) && (
                      <img src={batchItems.find((b) => b.id === selectedBatchId)!.preview} alt="" />
                    )}
                  </div>
                  <div className="batch-set-thumbs">
                    {batchItems.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={`batch-set-thumb ${selectedBatchId === item.id ? 'selected' : ''}`}
                        onClick={() => setSelectedBatchId(item.id)}
                      >
                        <img src={item.preview} alt="" />
                      </button>
                    ))}
                  </div>
                </div>
                <div className="batch-set-detail">
                  <h4 className="batch-set-detail-title">Description</h4>
                  {selectedBatchId && batchItems.find((b) => b.id === selectedBatchId) && (() => {
                    const item = batchItems.find((b) => b.id === selectedBatchId)!;
                    return (
                      <>
                        {item.description?.description_parts && (
                          <div className="batch-set-desc-parts">
                            {Object.entries(item.description.description_parts).map(([k, v]) => (
                              <div key={k} className="batch-set-desc-row"><span className="key">{k}</span><span className="val">{String(v)}</span></div>
                            ))}
                          </div>
                        )}
                        {item.description?.description_schema != null && (
                          <pre className="batch-set-json">{JSON.stringify(item.description.description_schema, null, 2)}</pre>
                        )}
                        {!item.description && <p className="hint">No description yet. Use Edit to add.</p>}
                        <div className="batch-set-detail-actions">
                          <button type="button" className="btn-icon" onClick={() => startEditBatchItem(item)} title="Edit">Edit</button>
                          <button type="button" className="btn-icon btn-remove" onClick={() => removeBatchItem(item.id)} title="Remove">Remove</button>
                        </div>
                      </>
                    );
                  })()}
                </div>
              </div>
            )}

            <div className="form-row form-actions" style={{ marginTop: '1.5rem' }}>
              <button type="button" className="btn-predict-set" onClick={runPredictSet} disabled={batchItems.length === 0 || predictLoading}>
                {predictLoading ? 'Predicting…' : `Predict (set only, ${batchItems.length} image(s))`}
              </button>
            </div>
          </section>

          {predictResult && (
            <section className="section result-section">
              <h2>Prediction result</h2>
              {predictResult.error && <p className="error">{predictResult.error}</p>}
              {predictResult.reid_debug && (
                <details className="reid-debug-details" style={{ marginBottom: '0.75rem' }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Re-ID debug</summary>
                  <pre className="edit-json-pre" style={{ marginTop: '0.35rem', fontSize: '0.75rem' }}>
                    {JSON.stringify(predictResult.reid_debug, null, 2)}
                  </pre>
                </details>
              )}
              {(predictResult.query_urls?.length ?? 0) > 0 ? (
                <div className="query-preview query-preview-set">
                  <h4>Query set ({predictResult.query_urls!.length} images)</h4>
                  <div className="query-set-thumbs">
                    {predictResult.query_urls!.map((u) => (
                      <img key={u} src={API_BASE + u} alt="" />
                    ))}
                  </div>
                </div>
              ) : predictResult.query_url ? (
                <div className="query-preview">
                  <img src={API_BASE + predictResult.query_url} alt="Query" />
                </div>
              ) : null}
              {predictResult.finalize && (
                <div className="finalize-banner">
                  <h3>Final ID (set → one rhino)</h3>
                  <p>
                    <strong>pid {predictResult.finalize.id}</strong> — score {predictResult.finalize.score?.toFixed(4)} —{' '}
                    {predictResult.finalize.method === 'majority_vote_per_image'
                      ? 'majority vote (per-image tops disagreed with mean embedding)'
                      : 'mean embedding over the set'}
                  </p>
                  {predictResult.finalize.per_image_conflict && (
                    <p className="hint warn">
                      Per-image top-1 IDs differed; mean-set top was {predictResult.finalize.mean_set_top1_id}, majority{' '}
                      {predictResult.finalize.majority_id} ({predictResult.finalize.majority_votes} votes).
                    </p>
                  )}
                </div>
              )}
              {predictResult.demo_not_in_gallery_url && (
                <p className="demo-weak-folder">
                  Weak-match copies (score &lt; threshold):{' '}
                  <a href={API_BASE + predictResult.demo_not_in_gallery_url} target="_blank" rel="noreferrer">
                    {predictResult.demo_not_in_gallery_url}
                  </a>{' '}
                  (folder + README for demo)
                </p>
              )}
              {predictResult.per_image && predictResult.per_image.length > 1 && (
                <div className="per-image-table-wrap">
                  <h4>Per-image (before finalize)</h4>
                  <table className="per-image-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>top1 pid</th>
                        <th>score</th>
                        <th>margin</th>
                      </tr>
                    </thead>
                    <tbody>
                      {predictResult.per_image.map((row, idx) => (
                        <tr key={row.path}>
                          <td>{idx + 1}</td>
                          <td>{row.top1_id}</td>
                          <td>{row.top1_score?.toFixed(4)}</td>
                          <td>{row.margin?.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {predictResult.top1 && (
                <div className="top1">
                  <h3>Gallery match (final)</h3>
                  <p>
                    ID: {predictResult.top1.id} | Score: {predictResult.top1.score?.toFixed(4)} | name:{' '}
                    {predictResult.top1.id_name ?? '-'}
                  </p>
                  {predictResult.top1.representative_image && (
                    <img src={API_BASE + '/uploads/' + predictResult.top1.representative_image} alt="Top1" />
                  )}
                </div>
              )}
              {predictResult.top_k && predictResult.top_k.length > 0 && (
                <div className="top5">
                  <h3>Top 5</h3>
                  <div className="top5-grid">
                    {predictResult.top_k.map((t) => (
                      <div key={t.rank} className="top5-item">
                        <span>#{t.rank} id={t.id} score={t.score?.toFixed(3)}</span>
                        {t.representative_image && (
                          <img src={API_BASE + '/uploads/' + t.representative_image} alt="" />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {predictResult.prediction_id != null && (
                <div className="report-actions">
                  <h3>Wrong match?</h3>
                  <p className="hint">Report to record the correct identity (no gallery confirm step).</p>
                  <button
                    type="button"
                    className="btn-report"
                    onClick={() => {
                      setReportPredictionId(predictResult.prediction_id!);
                      setReportCorrectIdentityId(null);
                    }}
                  >
                    Report wrong prediction
                  </button>
                </div>
              )}
            </section>
          )}

          {reportPredictionId != null && isReID && (
            <div className="modal-overlay" onClick={() => { setReportPredictionId(null); setReportCorrectIdentityId(null); }}>
              <div className="modal-content report-modal" onClick={(e) => e.stopPropagation()}>
                <h3>Report: select correct identity for prediction #{reportPredictionId}</h3>
                <select value={reportCorrectIdentityId ?? ''} onChange={(e) => setReportCorrectIdentityId(Number(e.target.value) || null)}>
                  <option value="">— Select identity —</option>
                  {activeIdentities.map((i) => (
                    <option key={i.id} value={i.id}>{i.name}{i.pid != null ? ` (pid=${i.pid})` : ''}</option>
                  ))}
                </select>
                <div className="modal-footer">
                  <button type="button" onClick={() => { setReportPredictionId(null); setReportCorrectIdentityId(null); }}>Cancel</button>
                  <button type="button" className="btn-modal-save" disabled={!reportCorrectIdentityId || reportSaving} onClick={async () => {
                    if (!reportCorrectIdentityId) return;
                    setReportSaving(true);
                    try {
                      await predictApi.report(reportPredictionId, reportCorrectIdentityId);
                      setReportPredictionId(null);
                      setReportCorrectIdentityId(null);
                      setPredictResult(null);
                      loadPredictionHistory().catch(() => {});
                    } catch (err) { console.error(err); }
                    finally { setReportSaving(false); }
                  }}>
                    {reportSaving ? 'Saving…' : 'Submit report'}
                  </button>
                </div>
              </div>
            </div>
          )}

          <section className="section">
            <h2>Prediction history</h2>
            <p className="section-note">
              Last {PREDICTION_HISTORY_LIMIT} predictions (newest first). Report if a match was wrong.
            </p>
            {isAdmin && (
              <label className="predict-history-admin-filter">
                <input
                  type="checkbox"
                  checked={historyReportedOnly}
                  onChange={(e) => setHistoryReportedOnly(e.target.checked)}
                />
                Reported only
              </label>
            )}
            <div className="predict-history-table-wrap">
              <table className="predict-history-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Query</th>
                    <th>Score</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {predictionHistory.map((h) => (
                    <tr key={h.id} className={h.reported ? 'reported' : ''}>
                      <td>{h.id}</td>
                      <td>
                        <img src={API_BASE + h.query_url} alt="" className="thumb" />
                      </td>
                      <td>{h.top1_score != null ? h.top1_score.toFixed(4) : '—'}</td>
                      <td>
                        {h.reported
                          ? `Reported → identity #${h.corrected_identity_id ?? '?'}`
                          : h.confirmed
                            ? 'Labeled'
                            : '—'}
                      </td>
                      <td>
                        {!h.reported && (
                          <button
                            type="button"
                            className="btn-report btn-report-small"
                            onClick={() => {
                              setReportPredictionId(h.id);
                              setReportCorrectIdentityId(null);
                            }}
                          >
                            Report
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {predictionHistory.length === 0 && (
              <p className="hint">No predictions yet. Run Predict on a set above.</p>
            )}
            <button type="button" className="btn-secondary" style={{ marginTop: '0.5rem' }} onClick={() => loadPredictionHistory()}>
              Refresh
            </button>
          </section>
        </div>
      ) : (
        <div className="rhino-list-page">
          <aside className="rhino-list-sidebar">
            <div className="sidebar-header">
              <h2>Rhino list</h2>
              <p className="section-note">Select a rhino to view and edit its images and descriptions.</p>
            </div>
            {isAdmin && (
              <form onSubmit={createRhino} className="rhino-list-add-form">
                <input placeholder="Name (e.g. Boma ID5301)" value={newRhinoName} onChange={(e) => setNewRhinoName(e.target.value)} />
                <input placeholder="pid (optional)" type="number" value={newRhinoPid} onChange={(e) => setNewRhinoPid(e.target.value)} />
                <button type="submit">Add rhino</button>
              </form>
            )}
            <div className="rhino-list-search-row">
              <input
                type="search"
                className="rhino-list-search-input"
                placeholder="Search by name…"
                value={identitySearchInput}
                onChange={(e) => setIdentitySearchInput(e.target.value)}
                aria-label="Search rhinos by name"
              />
            </div>
            <div className="rhino-list-pagination">
              <button
                type="button"
                className="btn-pagination"
                disabled={identityListPage <= 1 || identitiesLoading}
                onClick={() => setIdentityListPage((p) => Math.max(1, p - 1))}
              >
                Prev
              </button>
              <span className="rhino-list-page-meta">
                {identitiesLoading ? 'Loading…' : `Page ${identityListPage} / ${identityListPages} · ${identityListTotal} total`}
              </span>
              <button
                type="button"
                className="btn-pagination"
                disabled={identityListPage >= identityListPages || identitiesLoading}
                onClick={() => setIdentityListPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
            <div className="rhino-list-scroll">
              {!identitiesLoading && activeIdentities.length === 0 && (
                <p className="hint" style={{ padding: '0.75rem', margin: 0 }}>
                  {identityListTotal === 0 && !identitySearchQ ? 'No rhinos yet. Add one above.' : 'No rhinos match your search.'}
                </p>
              )}
              {activeIdentities.map((i) => (
                <div
                  key={i.id}
                  className={`rhino-list-card ${selectedIdentityId === i.id ? 'selected' : ''} ${editingIdentityId === i.id ? 'editing' : ''}`}
                >
                  {editingIdentityId === i.id ? (
                    <form onSubmit={saveEditIdentity} className="rhino-edit-form" onClick={(e) => e.stopPropagation()}>
                      <input value={editIdentityName} onChange={(e) => setEditIdentityName(e.target.value)} placeholder="Name" />
                      <input type="number" placeholder="pid" value={editIdentityPid} onChange={(e) => setEditIdentityPid(e.target.value)} />
                      <button type="submit">Save</button>
                      <button type="button" onClick={() => setEditingIdentityId(null)}>Cancel</button>
                    </form>
                  ) : (
                    <>
                      <div className="rhino-avatar" aria-hidden>{i.name.charAt(0)}</div>
                      <div
                        className="rhino-info"
                        onClick={() => {
                          setSelectedIdentityId(i.id);
                          setSelectedIdentitySummary(i);
                        }}
                      >
                        <span className="rhino-name">{i.name}</span>
                        {i.pid != null && <span className="rhino-pid">pid={i.pid}</span>}
                      </div>
                      {isAdmin && (
                        <div className="rhino-actions" onClick={(e) => e.stopPropagation()}>
                          <button type="button" onClick={() => startEditIdentity(i)}>Edit</button>
                          <button type="button" className="deactivate-btn" onClick={() => deactivateRhino(i.id)}>Deactivate</button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          </aside>

          <div className="rhino-detail-panel">
      {selectedIdentityId != null && selectedIdentity ? (
        <>
            <div className="rhino-detail-header">
              <button
                type="button"
                className="back-link"
                onClick={() => {
                  setSelectedIdentityId(null);
                  setSelectedIdentitySummary(null);
                }}
              >
                ← Back to list
              </button>
              <h2>{selectedIdentity.name}</h2>
              {selectedIdentity.pid != null && <span className="rhino-pid" style={{ display: 'block', marginTop: '0.25rem' }}>pid={selectedIdentity.pid}</span>}
            </div>
            <div className="rhino-detail-body">
          <section className="detail-section">
            <h3>Add image</h3>
            <p className="section-note">Upload one image → crop, optional manual ticks → Add (draft). Use the eye icon on an image for part crops + hybrid LLM.</p>
            <div
              className={`gallery-drop-zone ${dragOver ? 'drag-over' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const files = getImageFiles(e.dataTransfer.files);
                if (files[0] && selectedIdentityId) {
                  resetPopupCropState();
                  setEditFile(files[0]);
                  setEditCroppedFile(null);
                  setEditDescForm({ left_ear: {}, right_ear: {}, head: {}, body: {} });
                  setEditDescPartNotes({ ...EMPTY_PART_NOTES });
                  setEditPendingId('single-upload');
                }
              }}
            >
              <p>Select one file to upload</p>
              <p className="hint">Or drag and drop one image.</p>
              <label className="btn-add-inline">
                Add image (1)
                <input
                  type="file"
                  accept="image/*"
                  multiple={false}
                  hidden
                  onChange={(e) => {
                    const files = getImageFiles(e.target.files);
                    if (files[0] && selectedIdentityId) {
                      resetPopupCropState();
                      setEditFile(files[0]);
                      setEditCroppedFile(null);
                      setEditDescForm({ left_ear: {}, right_ear: {}, head: {}, body: {} });
                      setEditDescPartNotes({ ...EMPTY_PART_NOTES });
                      setEditPendingId('single-upload');
                    }
                    e.target.value = '';
                  }}
                />
              </label>
            </div>
          </section>

          <section className="detail-section rhino-description-section">
            <h3>General description (example)</h3>
            <div className="rhino-description-grid">
              {(['left_ear', 'right_ear', 'head', 'body'] as const).map((part) => (
                <div key={part} className="rhino-description-box example">
                  <div className="box-label">{DESCRIPTION_PART_LABELS[part]}</div>
                  <div className="box-content">{EXAMPLE_RHINO_DESCRIPTION[part]}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="detail-section">
            <h3>Images &amp; descriptions</h3>
            <div className="rhino-image-filter" style={{ marginBottom: '0.75rem' }}>
              <span className="filter-label">Status:</span>
              {(['all', 'draft', 'pending_review', 'junk', 'confirmed'] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`filter-btn ${imageFilter === f ? 'active' : ''}`}
                  onClick={() => setImageFilter(f)}
                >
                  {f === 'all'
                    ? 'All'
                    : f === 'draft'
                    ? 'Draft'
                    : f === 'pending_review'
                    ? 'Pending review'
                    : f === 'junk'
                    ? 'Junk'
                    : 'Confirmed'}
                </button>
              ))}
            </div>
            <p className="section-note" style={{ marginBottom: '0.75rem' }}>
              Draft = predicted candidate; Pending review = reported/waiting admin; Junk = invalid/non-rhino.
            </p>
            <div className="rhino-detail-grid">
              {images.map((img) => {
                const descText = img.description_parts ? Object.entries(img.description_parts).map(([k, v]) => v && `${k}: ${v}`).filter(Boolean).join(' · ') : '—';
                return (
                <div key={img.id} className="rhino-image-card">
                  <div className="card-image-wrap">
                    <img src={API_BASE + img.url} alt="" />
                    <div className="card-badges">
                      {img.confirmed ? <span className="badge">Approved</span> : <span className="badge badge-pending">Pending</span>}
                      {img.description_source === 'manual' && <span className="badge badge-manual">Manual</span>}
                      {img.description_source === 'o4-mini' && <span className="badge badge-o4">o4-mini</span>}
                    </div>
                  </div>
                  <div className="card-body">
                    <div className="card-desc" title={descText}>{descText}</div>
                    <div className="card-actions">
                      {!img.confirmed && <button type="button" onClick={() => confirmImage(img.id)}>Approve</button>}
                      <button type="button" className="btn-deactivate" onClick={() => deactivateImage(img.id)}>Deactivate</button>
                      <button type="button" onClick={() => setJsonViewId(jsonViewId === img.id ? null : img.id)}>
                        {jsonViewId === img.id ? 'Hide JSON' : 'JSON'}
                      </button>
                      <Link
                        className="btn-icon btn-icon-eye"
                        to={`/${img.identity_id}/img/${img.id}`}
                        title="View and edit (parts + description)"
                        aria-label="View and edit capture"
                      >
                        <EyeIcon />
                      </Link>
                      <button
                        type="button"
                        onClick={() => setExpandedId(expandedId === img.id ? null : img.id)}
                        title="Tick-based manual description"
                      >
                        {expandedId === img.id ? 'Hide manual' : 'Manual'}
                      </button>
                    </div>
                  {jsonViewId === img.id && (
                    <div className="card-expand rhino-json-view">
                      <strong>Description (JSON)</strong>
                      <pre className="desc-json">
                        {JSON.stringify(
                          {
                            description_parts: img.description_parts ?? null,
                            descriptions_four_parts:
                              img.description_schema &&
                              typeof img.description_schema === 'object' &&
                              'descriptions_four_parts' in (img.description_schema as object)
                                ? (img.description_schema as { descriptions_four_parts?: unknown }).descriptions_four_parts
                                : null,
                            description_schema: img.description_schema ?? null,
                            description_source: img.description_source ?? null,
                          },
                          null,
                          2
                        )}
                      </pre>
                    </div>
                  )}
                  {expandedId === img.id && (
                    <div className="description-panel">
                      <button type="button" onClick={() => runO4mini(img.id)} disabled={o4LoadingId !== null}>
                        {o4LoadingId === img.id ? 'Running o4-mini...' : 'Run o4-mini (1 image)'}
                      </button>
                      <div className="manual-options">
                        <h4>Manual description (tick options)</h4>
                        {(['left_ear', 'right_ear', 'head', 'body'] as const).map((part) => (
                          <div key={part} className="manual-part">
                            <strong>{part}</strong>
                            {part === 'left_ear' || part === 'right_ear' ? (
                              <div className="ear-tear-block">
                                <p className="hint" style={{ margin: '0 0 0.5rem' }}>
                                  Add one row per torn area. No rows = ear intact.
                                </p>
                                {(manualEarTears[img.id]?.[part] ?? []).map((row, ti) => (
                                  <div key={ti} className="ear-tear-row">
                                    <span className="ear-tear-row-label">Tear {ti + 1}</span>
                                    <label>
                                      notches
                                      <select
                                        value={row.notches}
                                        onChange={(e) => {
                                          const v = e.target.value;
                                          setManualEarTears((prev) => {
                                            const cur = prev[img.id] || { left_ear: [], right_ear: [] };
                                            const list = [...(cur[part] || [])];
                                            list[ti] = { ...list[ti], notches: v };
                                            return { ...prev, [img.id]: { ...cur, [part]: list } };
                                          });
                                        }}
                                      >
                                        {MANUAL_OPTIONS[part].notches.map((o) => (
                                          <option key={o || 'z'} value={o}>{o || '—'}</option>
                                        ))}
                                      </select>
                                    </label>
                                    <label>
                                      position
                                      <select
                                        value={row.position}
                                        onChange={(e) => {
                                          const v = e.target.value;
                                          setManualEarTears((prev) => {
                                            const cur = prev[img.id] || { left_ear: [], right_ear: [] };
                                            const list = [...(cur[part] || [])];
                                            list[ti] = { ...list[ti], position: v };
                                            return { ...prev, [img.id]: { ...cur, [part]: list } };
                                          });
                                        }}
                                      >
                                        {MANUAL_OPTIONS[part].position.map((o) => (
                                          <option key={o || 'z'} value={o}>{o || '—'}</option>
                                        ))}
                                      </select>
                                    </label>
                                    <label title="Round hole in ear center">
                                      central_hole
                                      <select
                                        value={row.central_hole}
                                        onChange={(e) => {
                                          const v = e.target.value;
                                          setManualEarTears((prev) => {
                                            const cur = prev[img.id] || { left_ear: [], right_ear: [] };
                                            const list = [...(cur[part] || [])];
                                            list[ti] = { ...list[ti], central_hole: v };
                                            return { ...prev, [img.id]: { ...cur, [part]: list } };
                                          });
                                        }}
                                      >
                                        {MANUAL_OPTIONS[part].central_hole.map((o) => (
                                          <option key={o || 'z'} value={o}>{o || '—'}</option>
                                        ))}
                                      </select>
                                    </label>
                                    <label className="ear-tear-note">
                                      note
                                      <input
                                        type="text"
                                        value={row.note}
                                        placeholder="Optional"
                                        onChange={(e) => {
                                          const v = e.target.value;
                                          setManualEarTears((prev) => {
                                            const cur = prev[img.id] || { left_ear: [], right_ear: [] };
                                            const list = [...(cur[part] || [])];
                                            list[ti] = { ...list[ti], note: v };
                                            return { ...prev, [img.id]: { ...cur, [part]: list } };
                                          });
                                        }}
                                      />
                                    </label>
                                    <button
                                      type="button"
                                      className="btn-remove-tear"
                                      onClick={() => {
                                        setManualEarTears((prev) => {
                                          const cur = prev[img.id] || { left_ear: [], right_ear: [] };
                                          const list = (cur[part] || []).filter((_, j) => j !== ti);
                                          return { ...prev, [img.id]: { ...cur, [part]: list } };
                                        });
                                      }}
                                    >
                                      Remove
                                    </button>
                                  </div>
                                ))}
                                <button
                                  type="button"
                                  className="btn-add-tear"
                                  onClick={() => {
                                    setManualEarTears((prev) => {
                                      const cur = prev[img.id] || { left_ear: [], right_ear: [] };
                                      return {
                                        ...prev,
                                        [img.id]: {
                                          ...cur,
                                          [part]: [...(cur[part] || []), emptyTear()],
                                        },
                                      };
                                    });
                                  }}
                                >
                                  + Add tear
                                </button>
                                <label className="ear-tuft-row">
                                  tuft{' '}
                                  <select
                                    value={manualForm[img.id]?.[part]?.tuft ?? ''}
                                    onChange={(e) => setManualOption(img.id, part, 'tuft', e.target.value)}
                                  >
                                    {MANUAL_OPTIONS[part].tuft.map((o) => (
                                      <option key={o || 'z'} value={o}>{o || '—'}</option>
                                    ))}
                                  </select>
                                </label>
                              </div>
                            ) : part === 'head' ? (
                              <>
                                <label>viewpoint <select value={manualForm[img.id]?.[part]?.viewpoint ?? ''} onChange={(e) => setManualOption(img.id, part, 'viewpoint', e.target.value)}>
                                  {['', 'front', 'side_left', 'side_right', 'rear'].map((o) => <option key={o || 'x'} value={o}>{o || '—'}</option>)}
                                </select></label>
                                <label>horn <select value={manualForm[img.id]?.[part]?.horn ?? ''} onChange={(e) => setManualOption(img.id, part, 'horn', e.target.value)}>
                                  {['', 'short blunt', 'long sharp', 'curved', 'straight'].map((o) => <option key={o || 'x'} value={o}>{o || '—'}</option>)}
                                </select></label>
                                <label>muzzle <select value={manualForm[img.id]?.[part]?.muzzle ?? ''} onChange={(e) => setManualOption(img.id, part, 'muzzle', e.target.value)}>
                                  {['', 'round', 'elongated'].map((o) => <option key={o || 'x'} value={o}>{o || '—'}</option>)}
                                </select></label>
                              </>
                            ) : (
                              <>
                                <label>skin <select value={manualForm[img.id]?.[part]?.skin ?? ''} onChange={(e) => setManualOption(img.id, part, 'skin', e.target.value)}>
                                  {['', 'smooth', 'moderate_wrinkle', 'heavy_wrinkle'].map((o) => <option key={o || 'x'} value={o}>{o || '—'}</option>)}
                                </select></label>
                                <label>size <select value={manualForm[img.id]?.[part]?.size ?? ''} onChange={(e) => setManualOption(img.id, part, 'size', e.target.value)}>
                                  {['', 'small', 'medium', 'large'].map((o) => <option key={o || 'x'} value={o}>{o || '—'}</option>)}
                                </select></label>
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                      <button type="button" onClick={() => saveManual(img)}>Save manual description</button>
                    </div>
                  )}
                  </div>
                </div>
              );
              })}
            </div>
          </section>
            </div>
        </>
      ) : (
            <div className="rhino-detail-empty">
              Select a rhino from the list to view its images and descriptions, or add a new one.
            </div>
      )}
          </div>
        </div>
      )}

      {(editPendingId || editBatchId) && editFile && (() => {
        const editingBatchItem = editBatchId ? batchItems.find((b) => b.id === editBatchId) : null;
        const closeModal = () => {
          resetPopupCropState();
          setEditPendingId(null);
          setEditBatchId(null);
          setEditFile(null);
          setEditCroppedFile(null);
          setEditPopupStep(1);
          setEditDescPartNotes({ ...EMPTY_PART_NOTES });
          setEditEarTears({ left_ear: [], right_ear: [] });
        };
        return (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content edit-reid-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">
                {editPopupStep === 1
                  ? (isReID ? 'Re-ID — step 1: crop' : 'Add image — step 1: crop')
                  : (isReID ? 'Re-ID — step 2: describe' : 'Add image — step 2: describe')}
              </h3>
              <button type="button" className="modal-close" onClick={closeModal} aria-label="Close">×</button>
              </div>

            {editPopupStep === 1 ? (
              <>
                <div className="edit-popup-step1">
                  <p className="edit-reid-hint">
                    Step 1 of 2 — <strong>Body</strong> from checkpoint on first visit; coming back from step 2 keeps
                    your frame (no re-detect). Adjust manually, then <strong>Next</strong>.
                  </p>
                  {step1BboxLoading ? (
                    <p className="hint" style={{ padding: '2.5rem', textAlign: 'center' }}>
                      Running body detector…
                    </p>
                  ) : (
                    <ImageCropper
                      key={
                        step1PixelRect
                          ? `s-${step1PixelRect.x}-${step1PixelRect.y}-${step1PixelRect.width}`
                          : 'full'
                      }
                      ref={step1CropperRef}
                      src={editFile}
                      onCropComplete={() => {}}
                      onCancel={closeModal}
                      commitMode="manual"
                      showCroppedPreview={false}
                      hideApplyButton
                      initialPixelRect={step1PixelRect}
                    />
                  )}
                </div>
                <div className="modal-footer">
                  <button type="button" className="btn-modal-cancel" onClick={closeModal}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn-modal-save"
                    disabled={step1BboxLoading}
                    onClick={async () => {
                      const rect = step1CropperRef.current?.getStencilInImagePixels();
                      if (rect) setStep1CommittedRect(rect);
                      const f = await step1CropperRef.current?.commitCrop();
                      if (f) setEditCroppedFile(f);
                      else setEditCroppedFile(null);
                      setEditPopupStep(2);
                    }}
                  >
                    Next
                  </button>
                </div>
              </>
            ) : editPopupStep === 2 ? (
              <>
                <div className="edit-popup-step2-detail-body">
                  <p className="section-note hint" style={{ marginTop: 0, marginBottom: '1rem' }}>
                    Step 2 — Part images from checkpoint once; <strong>eye</strong> = manual crop that part (no
                    re-detect). <button type="button" className="btn-link-inline" onClick={() => setEditPopupStep(1)}>
                      ← Main crop (step 1)
                    </button>
                  </p>
                  {editingBatchItem?.description && (
                    <div className="edit-current-json" style={{ marginBottom: '1rem' }}>
                      <p className="edit-reid-hint">Current description (JSON):</p>
                      <pre className="edit-json-pre">{JSON.stringify(editingBatchItem.description, null, 2)}</pre>
                    </div>
                  )}
                  <section className="detail-section-parts" style={{ marginBottom: '1rem' }}>
                    <div className="detail-part-rows">
                      {POPUP_PART_ORDER.map((partKey) => (
                        <div key={partKey} className="detail-part-row">
                          <div className="detail-part-row-label">{DESCRIPTION_PART_LABELS[partKey]}</div>
                          <div className="detail-part-row-body">
                            <div className="detail-part-thumb-wrap">
                              {step2PartsLoading ? (
                                <div
                                  className="detail-part-thumb"
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    minHeight: 120,
                                  }}
                                >
                                  <span className="hint" style={{ fontSize: '0.75rem' }}>
                                    Detecting…
                                  </span>
                                </div>
                              ) : step2PartPreviews[partKey] ? (
                                <div className="detail-part-thumb">
                                  <img src={step2PartPreviews[partKey]} alt="" />
                                  <button
                                    type="button"
                                    className="detail-thumb-edit"
                                    title="Crop this part"
                                    aria-label="Crop this part"
                                    onClick={() => void openPartManualCrop(partKey)}
                                  >
                                    <EyeIcon />
                                  </button>
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  className="detail-part-thumb detail-part-thumb-empty"
                                  onClick={() => void openPartManualCrop(partKey)}
                                  aria-label="Manual crop this part"
                                >
                                  <span className="detail-part-thumb-placeholder">No detection — tap to crop</span>
                                  <span className="detail-thumb-edit detail-thumb-edit-center" aria-hidden>
                                    <EyeIcon />
                                  </span>
                                </button>
                              )}
                            </div>
                            <div className="detail-part-form-col">
                              {partKey === 'left_ear' || partKey === 'right_ear' ? (
                                <>
                                  <p className="hint" style={{ margin: '0 0 0.5rem' }}>
                                    List each torn area (row). No rows = intact ear.
                                  </p>
                                  {(editEarTears[partKey] || []).map((row, ti) => (
                                    <div key={ti} className="ear-tear-row ear-tear-row-popup">
                                      <span className="ear-tear-row-label">Tear {ti + 1}</span>
                                      <label>
                                        notches
                                        <select
                                          value={row.notches}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            setEditEarTears((prev) => {
                                              const list = [...(prev[partKey] || [])];
                                              list[ti] = { ...list[ti], notches: v };
                                              return { ...prev, [partKey]: list };
                                            });
                                          }}
                                        >
                                          {MANUAL_OPTIONS[partKey].notches.map((o) => (
                                            <option key={o || 'z'} value={o}>{o || '—'}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label>
                                        position
                                        <select
                                          value={row.position}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            setEditEarTears((prev) => {
                                              const list = [...(prev[partKey] || [])];
                                              list[ti] = { ...list[ti], position: v };
                                              return { ...prev, [partKey]: list };
                                            });
                                          }}
                                        >
                                          {MANUAL_OPTIONS[partKey].position.map((o) => (
                                            <option key={o || 'z'} value={o}>{o || '—'}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label>
                                        central_hole
                                        <select
                                          value={row.central_hole}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            setEditEarTears((prev) => {
                                              const list = [...(prev[partKey] || [])];
                                              list[ti] = { ...list[ti], central_hole: v };
                                              return { ...prev, [partKey]: list };
                                            });
                                          }}
                                        >
                                          {MANUAL_OPTIONS[partKey].central_hole.map((o) => (
                                            <option key={o || 'z'} value={o}>{o || '—'}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label className="ear-tear-note">
                                        note
                                        <input
                                          type="text"
                                          value={row.note}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            setEditEarTears((prev) => {
                                              const list = [...(prev[partKey] || [])];
                                              list[ti] = { ...list[ti], note: v };
                                              return { ...prev, [partKey]: list };
                                            });
                                          }}
                                        />
                                      </label>
                                      <button
                                        type="button"
                                        className="btn-remove-tear"
                                        onClick={() =>
                                          setEditEarTears((prev) => ({
                                            ...prev,
                                            [partKey]: (prev[partKey] || []).filter((_, j) => j !== ti),
                                          }))
                                        }
                                      >
                                        Remove
                                      </button>
                                    </div>
                                  ))}
                                  <button
                                    type="button"
                                    className="btn-add-tear"
                                    onClick={() =>
                                      setEditEarTears((prev) => ({
                                        ...prev,
                                        [partKey]: [...(prev[partKey] || []), emptyTear()],
                                      }))
                                    }
                                  >
                                    + Add tear
                                  </button>
                                  <label className="ear-tuft-row">
                                    tuft{' '}
                                    <select
                                      value={editDescForm[partKey]?.tuft ?? ''}
                                      onChange={(e) =>
                                        setEditDescForm((f) => ({
                                          ...f,
                                          [partKey]: { ...(f[partKey] || {}), tuft: e.target.value },
                                        }))
                                      }
                                    >
                                      {MANUAL_OPTIONS[partKey].tuft.map((o) => (
                                        <option key={o || 'z'} value={o}>{o || '—'}</option>
                                      ))}
                                    </select>
                                  </label>
                                </>
                              ) : (
                                <>
                                  <div className="detail-manual-selects detail-manual-selects-row">
                                    {Object.entries(MANUAL_OPTIONS[partKey]).map(([optKey, options]) => (
                                      <span key={optKey} className="detail-manual-select-wrap">
                                        <label>{optKey}</label>
                                        <select
                                          value={editDescForm[partKey]?.[optKey] ?? ''}
                                          onChange={(e) =>
                                            setEditDescForm((f) => ({
                                              ...f,
                                              [partKey]: { ...(f[partKey] || {}), [optKey]: e.target.value },
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
                                </>
                              )}
                              <label className="detail-part-note-label">
                                Note (this part)
                                <textarea
                                  rows={2}
                                  className="detail-part-note"
                                  placeholder="Optional"
                                  value={editDescPartNotes[partKey]}
                                  onChange={(e) =>
                                    setEditDescPartNotes((n) => ({ ...n, [partKey]: e.target.value }))
                                  }
                                />
                              </label>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                  {isReID ? (
                    <p className="edit-reid-note">Save runs o4-mini to build JSON and adds the image to the set.</p>
                  ) : (
                    <p className="edit-reid-note">
                      <strong>Add</strong> uploads as draft with manual text, or runs o4-mini on the crop if manual fields are empty.
                    </p>
                  )}
                </div>
                <div className="modal-footer">
                  <button type="button" className="btn-modal-cancel" onClick={() => setEditPopupStep(1)}>Back</button>
                  <button type="button" className="btn-modal-cancel" onClick={closeModal}>Cancel</button>
                  {isReID ? (
                <button type="button" className="btn-modal-save" disabled={describeSaving} onClick={saveFromEditPopup}>
                  {describeSaving ? 'Saving…' : 'Save'}
                </button>
              ) : (
                <button type="button" className="btn-modal-save" disabled={reidSaving} onClick={handleReIDSave}>
                      {reidSaving ? 'Adding…' : 'Add'}
                </button>
              )}
            </div>
              </>
            ) : null}
          </div>
        </div>
        );
      })()}

      {(editPendingId || editBatchId) &&
        editFile instanceof File &&
        partCropTarget &&
        partCropInitialRect && (
          <div
            className="modal-overlay"
            style={{ zIndex: 5000 }}
            onClick={() => {
              setPartCropTarget(null);
              setPartCropInitialRect(null);
            }}
          >
            <div
              className="modal-content edit-reid-modal"
              style={{ maxWidth: 720 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="modal-header">
                <h3 className="modal-title">Manual crop: {DESCRIPTION_PART_LABELS[partCropTarget]}</h3>
                <button
                  type="button"
                  className="modal-close"
                  onClick={() => {
                    setPartCropTarget(null);
                    setPartCropInitialRect(null);
                  }}
                  aria-label="Close"
                >
                  ×
                </button>
              </div>
              <ImageCropper
                key={`pc-${partCropTarget}-${partCropInitialRect.x}-${partCropInitialRect.y}`}
                ref={partCropperRef}
                src={editFile}
                initialPixelRect={partCropInitialRect}
                onCropComplete={() => {}}
                commitMode="manual"
                showCroppedPreview={false}
                onCancel={() => {
                  setPartCropTarget(null);
                  setPartCropInitialRect(null);
                }}
              />
              <div className="modal-footer">
                <button
                  type="button"
                  className="btn-modal-cancel"
                  onClick={() => {
                    setPartCropTarget(null);
                    setPartCropInitialRect(null);
                  }}
                >
                  Cancel
                </button>
                <button type="button" className="btn-modal-save" onClick={() => void applyPartManualCrop()}>
                  Apply
                </button>
              </div>
            </div>
          </div>
        )}
    </div>
  );
}
