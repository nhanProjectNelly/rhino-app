import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (e) => {
    if (e.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(e);
  }
);

export const auth = {
  login: (username: string, password: string) =>
    api.post<{ access_token: string }>('/auth/login', { username, password }),
  register: (username: string, password: string) =>
    api.post<{ access_token: string }>('/auth/register', { username, password }),
  me: () => api.get('/auth/me'),
};

export const lists = {
  getAll: () => api.get('/lists'),
  create: (name: string, list_type: 'high_quality' | 'images') =>
    api.post('/lists', { name, list_type }),
  get: (id: number) => api.get(`/lists/${id}`),
  getIdentities: (id: number) => api.get(`/lists/${id}/identities`),
  createIdentity: (listId: number, name: string) =>
    api.post(`/lists/${listId}/identities`, null, { params: { name } }),
  migrate: (source_list_id: number, target_list_id: number, identity_ids?: number[]) =>
    api.post('/lists/migrate', { source_list_id, target_list_id, identity_ids }),
};

export type GalleryIdentityRow = { id: number; name: string; pid: number | null; is_active?: boolean };
export type GalleryIdentitiesPage = {
  items: GalleryIdentityRow[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export const gallery = {
  getIdentities: (opts?: {
    include_inactive?: boolean;
    q?: string;
    page?: number;
    page_size?: number;
    all?: boolean;
  }) => {
    const params: Record<string, string | number | boolean> = {};
    if (opts?.include_inactive) params.include_inactive = true;
    if (opts?.all) {
      params.all = true;
    } else {
      params.page = opts?.page ?? 1;
      params.page_size = opts?.page_size ?? 20;
    }
    if (opts?.q != null && String(opts.q).trim() !== '') params.q = String(opts.q).trim();
    return api.get<GalleryIdentitiesPage>('/gallery/identities', { params });
  },
  createIdentity: (name: string, pid?: number | null) =>
    api.post('/gallery/identities', { name, pid }),
  updateIdentity: (id: number, data: { name?: string; pid?: number | null }) =>
    api.patch(`/gallery/identities/${id}`, data),
  deactivateIdentity: (id: number) => api.patch(`/gallery/identities/${id}/deactivate`),
  getImages: (
    identity_id?: number,
    include_inactive?: boolean,
    confirmed?: boolean,
    review_status?: 'draft' | 'pending_review' | 'junk' | 'confirmed'
  ) =>
    api.get('/gallery/images', {
      params: {
        ...(identity_id != null ? { identity_id } : {}),
        ...(include_inactive ? { include_inactive: true } : {}),
        ...(confirmed !== undefined ? { confirmed } : {}),
        ...(review_status ? { review_status } : {}),
      },
    }),
  upload: (identity_id: number, file: File, part_type?: string, confirmed = false) => {
    const fd = new FormData();
    fd.append('identity_id', String(identity_id));
    if (part_type) fd.append('part_type', part_type);
    fd.append('confirmed', String(confirmed));
    fd.append('file', file);
    return api.post('/gallery/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  uploadWithDescription: (
    identity_id: number,
    file: File,
    opts: {
      part_type?: string;
      confirmed?: boolean;
      left_ear?: string;
      right_ear?: string;
      head?: string;
      body?: string;
      run_llm?: boolean;
      descriptions_four_parts_json?: string;
    } = {}
  ) => {
    const fd = new FormData();
    fd.append('identity_id', String(identity_id));
    if (opts.part_type) fd.append('part_type', opts.part_type);
    fd.append('confirmed', String(opts.confirmed ?? false));
    fd.append('run_llm', String(opts.run_llm ?? true));
    if (opts.left_ear != null) fd.append('left_ear', opts.left_ear);
    if (opts.right_ear != null) fd.append('right_ear', opts.right_ear);
    if (opts.head != null) fd.append('head', opts.head);
    if (opts.body != null) fd.append('body', opts.body);
    if (opts.descriptions_four_parts_json) fd.append('descriptions_four_parts_json', opts.descriptions_four_parts_json);
    fd.append('file', file);
    return api.post('/gallery/upload-with-description', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  partCropFromParent: (identity_id: number, parent_image_id: number, part_type: string, file: File) => {
    const fd = new FormData();
    fd.append('identity_id', String(identity_id));
    fd.append('parent_image_id', String(parent_image_id));
    fd.append('part_type', part_type);
    fd.append('file', file);
    return api.post<{ id: number; url: string; created: boolean }>(
      '/gallery/images/part-crop-from-parent',
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
  },
  updateImage: (image_id: number, file?: File, parts?: { left_ear?: string; right_ear?: string; head?: string; body?: string }) => {
    const fd = new FormData();
    if (parts?.left_ear != null) fd.append('left_ear', parts.left_ear);
    if (parts?.right_ear != null) fd.append('right_ear', parts.right_ear);
    if (parts?.head != null) fd.append('head', parts.head);
    if (parts?.body != null) fd.append('body', parts.body);
    if (file) fd.append('file', file);
    return api.patch(`/gallery/images/${image_id}`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  confirmImage: (image_id: number) => api.patch(`/gallery/images/${image_id}/confirm`),
  deactivateImage: (image_id: number) => api.patch(`/gallery/images/${image_id}/deactivate`),
  saveManualDescription: (image_id: number, data: { left_ear?: string; right_ear?: string; head?: string; body?: string }) =>
    api.patch(`/gallery/images/${image_id}/description`, data),
  describeO4mini: (image_id: number) =>
    api.post<{
      anchor_image_id?: number;
      description_parts?: Record<string, string>;
      description_schema?: unknown;
      description_source?: string;
    }>(`/gallery/images/${image_id}/describe-o4mini`),
  getCaptureDetail: (identity_id: number, image_id: number) =>
    api.get<{
      identity_id: number;
      identity_name: string;
      anchor_image_id: number;
      source_stem: string | null;
      anchor: { id: number; url: string };
      slots: Record<
        string,
        | {
            id: number;
            url: string;
            parent_url: string;
            is_anchor_fallback?: boolean;
          }
        | null
      >;
      canonical_description_parts: Record<string, string> | null;
      four_parts_key_default: string;
    }>('/gallery/images/' + image_id + '/capture-detail', { params: { identity_id } }),
  getCaptures: (identity_id: number) =>
    api.get<{
      identity_id: number;
      captures: Array<{
        source_stem: string | null;
        anchor_image_id: number;
        active_version_id: number | null;
        canonical_description_parts: Record<string, string> | null;
        parts: Record<
          string,
          {
            id: number;
            url: string;
            part_type: string | null;
            parent_image_id: number | null;
            parent_url?: string;
            description_parts?: Record<string, string> | null;
          }
        >;
      }>;
    }>(`/gallery/identities/${identity_id}/captures`),
  getDescriptionVersions: (image_id: number) =>
    api.get<{
      anchor_image_id: number;
      versions: Array<{
        id: number;
        label: string | null;
        is_active: boolean;
        created_at: string | null;
        created_from_version_id: number | null;
        description_parts: Record<string, string> | null;
      }>;
    }>(`/gallery/images/${image_id}/description-versions`),
  activateDescriptionVersion: (image_id: number, version_id: number) =>
    api.post(`/gallery/images/${image_id}/description-versions/${version_id}/activate`),
  createDescriptionVersion: (
    image_id: number,
    body: {
      left_ear?: string;
      right_ear?: string;
      head?: string;
      body?: string;
      label?: string;
      from_version_id?: number | null;
      make_active?: boolean;
    }
  ) => api.post(`/gallery/images/${image_id}/description-versions`, body),
  describe: (
    identity_id: number,
    image_id: string,
    part_ids: { left_ear_id?: number; right_ear_id?: number; head_id?: number; body_id?: number },
    opts?: {
      left_ear_text?: string;
      right_ear_text?: string;
      head_text?: string;
      body_text?: string;
      four_parts_key?: string;
      llm_regenerate_with_form_hints?: boolean;
      anchor_image_id?: number;
    }
  ) => {
    const fd = new FormData();
    fd.append('identity_id', String(identity_id));
    fd.append('image_id', image_id);
    if (part_ids.left_ear_id) fd.append('left_ear_id', String(part_ids.left_ear_id));
    if (part_ids.right_ear_id) fd.append('right_ear_id', String(part_ids.right_ear_id));
    if (part_ids.head_id) fd.append('head_id', String(part_ids.head_id));
    if (part_ids.body_id) fd.append('body_id', String(part_ids.body_id));
    if (opts?.left_ear_text) fd.append('left_ear_text', opts.left_ear_text);
    if (opts?.right_ear_text) fd.append('right_ear_text', opts.right_ear_text);
    if (opts?.head_text) fd.append('head_text', opts.head_text);
    if (opts?.body_text) fd.append('body_text', opts.body_text);
    if (opts?.four_parts_key) fd.append('four_parts_key', opts.four_parts_key);
    if (opts?.llm_regenerate_with_form_hints) fd.append('llm_regenerate_with_form_hints', 'true');
    if (opts?.anchor_image_id != null) fd.append('anchor_image_id', String(opts.anchor_image_id));
    return api.post<{
      part_texts: Record<string, string>;
      descriptions_four_parts: Record<string, Record<string, string>>;
      schema: unknown;
      llm_parts_used: string[];
      manual_parts_used: string[];
    }>('/gallery/images/describe', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
};

export const predict = {
  describeFile: (
    file: File,
    hints?: Partial<Record<'left_ear' | 'right_ear' | 'head' | 'body', string>>
  ) => {
    const fd = new FormData();
    fd.append('file', file);
    if (hints?.left_ear) fd.append('left_ear_text', hints.left_ear);
    if (hints?.right_ear) fd.append('right_ear_text', hints.right_ear);
    if (hints?.head) fd.append('head_text', hints.head);
    if (hints?.body) fd.append('body_text', hints.body);
    return api.post<{ description_schema: unknown; description_parts: Record<string, string> }>(
      '/predict/describe-file',
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
  },
  upload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return api.post('/predict/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  /** Multi-image set → one Re-ID id (backend aggregates embeddings + majority finalize). */
  uploadSet: (
    files: File[],
    descriptionPartsPerImage?: Array<Record<string, string> | null | undefined>
  ) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));
    if (
      descriptionPartsPerImage &&
      descriptionPartsPerImage.length === files.length
    ) {
      const list = descriptionPartsPerImage.map((p) => ({
        left_ear: String(p?.left_ear ?? ''),
        right_ear: String(p?.right_ear ?? ''),
        head: String(p?.head ?? ''),
        body: String(p?.body ?? ''),
      }));
      fd.append('description_parts_list_json', JSON.stringify(list));
    }
    return api.post('/predict/upload-set', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  confirm: (prediction_id: number, identity_id: number, add_to_gallery = true) => {
    const fd = new FormData();
    fd.append('prediction_id', String(prediction_id));
    fd.append('identity_id', String(identity_id));
    fd.append('add_to_gallery', String(add_to_gallery));
    return api.post('/predict/confirm', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  report: (prediction_id: number, correct_identity_id: number) => {
    const fd = new FormData();
    fd.append('prediction_id', String(prediction_id));
    fd.append('correct_identity_id', String(correct_identity_id));
    return api.post('/predict/report', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  assign: (prediction_id: number, identity_id: number) => {
    const fd = new FormData();
    fd.append('prediction_id', String(prediction_id));
    fd.append('identity_id', String(identity_id));
    return api.post('/predict/assign', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  setTop: (prediction_id: number, top1_identity_id: number) => {
    const fd = new FormData();
    fd.append('prediction_id', String(prediction_id));
    fd.append('top1_identity_id', String(top1_identity_id));
    return api.patch('/predict/top', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  history: (limit = 50, confirmed?: boolean, reportedOnly?: boolean) =>
    api.get('/predict/history', {
      params: {
        limit,
        ...(confirmed !== undefined ? { confirmed } : {}),
        ...(reportedOnly === true ? { reported_only: true } : {}),
      },
    }),
  reviewQueue: (status?: 'draft' | 'pending_review' | 'junk') =>
    api.get('/predict/review-queue', { params: { ...(status ? { status } : {}) } }),
  reviewAssign: (prediction_id: number, identity_id: number) => {
    const fd = new FormData();
    fd.append('identity_id', String(identity_id));
    return api.post(`/predict/review/${prediction_id}/assign`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  reviewCreateIdentity: (prediction_id: number, name: string, pid?: number | null) =>
    api.post(`/predict/review/${prediction_id}/create-identity`, { name, pid }),
  reviewMarkJunk: (prediction_id: number) =>
    api.post(`/predict/review/${prediction_id}/mark-junk`),
};

export const crop = {
  crop: (file: File, x: number, y: number, width: number, height: number) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('x', String(x));
    fd.append('y', String(y));
    fd.append('width', String(width));
    fd.append('height', String(height));
    return api.post('/crop/image', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  suggestBbox: (file: File, target: 'body' | 'head' = 'body') => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('target', target);
    return api.post<{
      x: number;
      y: number;
      width: number;
      height: number;
      image_width: number;
      image_height: number;
      source: string;
      weights?: string | null;
    }>('/crop/suggest-bbox', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
  suggestPartBboxes: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return api.post<{
      parts: Record<
        'body' | 'head' | 'left_ear' | 'right_ear',
        { x: number; y: number; width: number; height: number } | null
      >;
      image_width: number;
      image_height: number;
    }>('/crop/suggest-part-bboxes', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  },
};

export default api;
