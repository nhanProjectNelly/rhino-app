import { useState, useEffect } from 'react';
import { predict as predictApi, gallery } from '../api';
import { ImageCropper } from '../components/ImageCropper';

const API_BASE = '';

type Identity = { id: number; name: string; pid: number | null };
type TopItem = { rank: number; id: number; id_name?: string; score: number; representative_image: string };

export function Predict() {
  const [file, setFile] = useState<File | null>(null);
  const [cropBeforeSubmit, setCropBeforeSubmit] = useState(false);
  const [result, setResult] = useState<{
    prediction_id?: number;
    query_url?: string;
    top_k?: TopItem[];
    top1?: TopItem;
    top1_identity_id?: number;
    nearest_images?: string[];
    error?: string;
  } | null>(null);
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [confirmIdentityId, setConfirmIdentityId] = useState<number | null>(null);
  const [addToGallery, setAddToGallery] = useState(true);
  const [history, setHistory] = useState<unknown[]>([]);

  const loadIdentities = () =>
    gallery.getIdentities({ all: true }).then((r) => setIdentities(r.data.items));
  const PREDICTION_HISTORY_LIMIT = 10;
  const loadHistory = () =>
    predictApi.history(PREDICTION_HISTORY_LIMIT).then((r) => setHistory(r.data));
  useEffect(() => { loadIdentities(); loadHistory(); }, []);

  const submitFile = async (f: File) => {
    setResult(null);
    try {
      const res = await predictApi.upload(f);
      setResult(res.data);
      loadHistory();
    } catch (err) {
      setResult({ error: (err as Error).message });
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (cropBeforeSubmit) {
      setFile(f);
    } else {
      submitFile(f);
    }
    e.target.value = '';
  };

  const handleCropComplete = (croppedFile: File) => {
    submitFile(croppedFile);
    setFile(null);
  };

  const confirmPrediction = async () => {
    if (!result?.prediction_id || !confirmIdentityId) return;
    try {
      await predictApi.confirm(result.prediction_id, confirmIdentityId, addToGallery);
      setConfirmIdentityId(null);
      setResult((r) => r ? { ...r, top1_identity_id: confirmIdentityId } : null);
      loadHistory();
    } catch (err) {
      console.error(err);
    }
  };

  const assignManually = async () => {
    if (!result?.prediction_id || !confirmIdentityId) return;
    try {
      await predictApi.assign(result.prediction_id, confirmIdentityId);
      setConfirmIdentityId(null);
      setResult((r) => r ? { ...r, top1_identity_id: confirmIdentityId } : null);
      loadHistory();
    } catch (err) {
      console.error(err);
    }
  };

  const setTop = async (identityId: number) => {
    if (!result?.prediction_id) return;
    try {
      await predictApi.setTop(result.prediction_id, identityId);
      setResult((r) => r ? { ...r, top1_identity_id: identityId } : null);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page predict-page">
      <h1>Re-identify rhino</h1>
      <p>Upload image (crop first if needed) → match to identity. Image and rhino info are stored in app assets and DB.</p>

      <section className="section">
        <div className="form-inline">
          <label>
            <input type="checkbox" checked={cropBeforeSubmit} onChange={(e) => setCropBeforeSubmit(e.target.checked)} />
            Crop image before submit
          </label>
          <label className="btn">
            Choose image
            <input type="file" accept="image/*" hidden onChange={handleFileSelect} />
          </label>
        </div>
        {file && (
          <div className="crop-modal">
            <ImageCropper
              src={file}
              onCropComplete={handleCropComplete}
              onCancel={() => setFile(null)}
            />
          </div>
        )}
      </section>

      {result && (
        <section className="section result-section">
          <h2>Result</h2>
          {result.error && <p className="error">{result.error}</p>}
          {result.query_url && (
            <div className="query-preview">
              <img src={API_BASE + result.query_url} alt="Query" />
            </div>
          )}
          {result.top1 && (
            <div className="top1">
              <h3>Top 1</h3>
              <p>ID: {result.top1.id} | Score: {result.top1.score?.toFixed(4)} | name: {result.top1.id_name ?? '-'}</p>
              {result.top1.representative_image && (
                <img src={API_BASE + '/uploads/' + result.top1.representative_image} alt="Top1" />
              )}
            </div>
          )}
          {result.top_k && result.top_k.length > 0 && (
            <div className="top5">
              <h3>Top 5 reference</h3>
              <div className="top5-grid">
                {result.top_k.map((t) => (
                  <div key={t.rank} className="top5-item">
                    <span>#{t.rank} id={t.id} score={t.score?.toFixed(3)}</span>
                    {t.representative_image && (
                      <img src={API_BASE + '/uploads/' + t.representative_image} alt="" />
                    )}
                    <button type="button" onClick={() => { const ident = identities.find((i) => i.pid === t.id); if (ident) setTop(ident.id); }}>Set as Top 1</button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="confirm-actions">
            <h3>Confirm / Assign manually</h3>
            <select value={confirmIdentityId ?? ''} onChange={(e) => setConfirmIdentityId(Number(e.target.value) || null)}>
              <option value="">Select identity</option>
              {identities.map((i) => (
                <option key={i.id} value={i.id}>{i.name}</option>
              ))}
            </select>
            <label>
              <input type="checkbox" checked={addToGallery} onChange={(e) => setAddToGallery(e.target.checked)} />
              Add to gallery when confirming
            </label>
            <button type="button" onClick={confirmPrediction} disabled={!confirmIdentityId}>Confirm (add to gallery)</button>
            <button type="button" onClick={assignManually} disabled={!confirmIdentityId}>Assign only</button>
          </div>
        </section>
      )}

      <section className="section">
        <h2>Prediction history</h2>
        <p className="section-note">Last {PREDICTION_HISTORY_LIMIT} predictions (newest first).</p>
        <ul className="history-list">
          {(history as { id: number; query_url: string; top1_identity_id?: number; confirmed?: boolean }[]).map((h) => (
            <li key={h.id}>
              <img src={API_BASE + h.query_url} alt="" className="thumb" />
              <span>id={h.id}</span>
              {h.confirmed && <span className="badge">confirmed</span>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
