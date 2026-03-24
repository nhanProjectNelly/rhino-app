import {
  useRef,
  useState,
  useEffect,
  useCallback,
  useImperativeHandle,
  forwardRef,
} from 'react';
import type { CropperRef } from 'react-advanced-cropper';
import { Cropper } from 'react-advanced-cropper';
import 'react-advanced-cropper/dist/style.css';

export type ImageCropperHandle = {
  /** Export current stencil as JPEG File (for Next without Apply). */
  commitCrop: () => Promise<File | null>;
  /** Stencil in natural image pixels (for restoring without re-detect). */
  getStencilInImagePixels: () => { x: number; y: number; width: number; height: number } | null;
};

type Props = {
  src: string | File;
  onCropComplete: (file: File) => void;
  onCancel?: () => void;
  showCroppedPreview?: boolean;
  commitMode?: 'live' | 'manual';
  /** Applied once on ready — pixel coords on the natural image (from /crop/suggest-bbox). */
  initialPixelRect?: { x: number; y: number; width: number; height: number } | null;
  /** When commitMode is manual, still hide the Apply button (parent commits via ref). */
  hideApplyButton?: boolean;
};

function canvasToFile(canvas: HTMLCanvasElement): Promise<File> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error('Failed to create blob'));
          return;
        }
        resolve(new File([blob], 'cropped.jpg', { type: 'image/jpeg' }));
      },
      'image/jpeg',
      0.95
    );
  });
}

export const ImageCropper = forwardRef<ImageCropperHandle, Props>(function ImageCropper(
  {
    src,
    onCropComplete,
    onCancel,
    showCroppedPreview = true,
    commitMode = 'live',
    initialPixelRect = null,
    hideApplyButton = false,
  },
  ref
) {
  const cropperRef = useRef<CropperRef>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [croppedPreviewUrl, setCroppedPreviewUrl] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const croppedPreviewUrlRef = useRef<string | null>(null);
  const onCropCompleteRef = useRef(onCropComplete);
  const updateTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stencilAppliedRef = useRef(false);
  onCropCompleteRef.current = onCropComplete;

  useImperativeHandle(ref, () => ({
    commitCrop: async () => {
      const cropper = cropperRef.current;
      if (!cropper) return null;
      const canvas = cropper.getCanvas();
      if (!canvas) return null;
      try {
        return await canvasToFile(canvas);
      } catch {
        return null;
      }
    },
    getStencilInImagePixels: () => {
      const c = cropperRef.current?.getCoordinates?.({ round: true });
      if (!c || c.width < 1 || c.height < 1) return null;
      return {
        x: Math.max(0, Math.round(c.left)),
        y: Math.max(0, Math.round(c.top)),
        width: Math.max(1, Math.round(c.width)),
        height: Math.max(1, Math.round(c.height)),
      };
    },
  }));

  const isFile = src instanceof File;
  useEffect(() => {
    if (!(isFile && src instanceof File)) {
      setObjectUrl(null);
      return;
    }
    const u = URL.createObjectURL(src);
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = u;
    setObjectUrl(u);
    return () => {
      /* revoke on unmount */
    };
  }, [isFile, src]);

  useEffect(() => {
    stencilAppliedRef.current = false;
  }, [initialPixelRect, src]);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
      if (croppedPreviewUrlRef.current) {
        URL.revokeObjectURL(croppedPreviewUrlRef.current);
        croppedPreviewUrlRef.current = null;
      }
      if (updateTimeoutRef.current) clearTimeout(updateTimeoutRef.current);
    };
  }, []);

  const imageSrc = isFile ? objectUrl : typeof src === 'string' ? src : '';

  const applyCrop = useCallback((notify: boolean) => {
    const cropper = cropperRef.current;
    if (!cropper) return;
    const canvas = cropper.getCanvas();
    if (!canvas) return;
    if (croppedPreviewUrlRef.current) URL.revokeObjectURL(croppedPreviewUrlRef.current);
    canvasToFile(canvas).then((file) => {
      const previewUrl = URL.createObjectURL(file);
      croppedPreviewUrlRef.current = previewUrl;
      setCroppedPreviewUrl(previewUrl);
      if (notify) onCropCompleteRef.current(file);
    });
  }, []);

  const handleChange = useCallback(() => {
    if (updateTimeoutRef.current) clearTimeout(updateTimeoutRef.current);
    updateTimeoutRef.current = setTimeout(() => {
      updateTimeoutRef.current = null;
      applyCrop(commitMode === 'live');
    }, 400);
  }, [applyCrop, commitMode]);

  const handleReady = useCallback(() => {
    const cropper = cropperRef.current;
    if (cropper && initialPixelRect && !stencilAppliedRef.current) {
      try {
        cropper.setCoordinates({
          left: initialPixelRect.x,
          top: initialPixelRect.y,
          width: initialPixelRect.width,
          height: initialPixelRect.height,
        });
        stencilAppliedRef.current = true;
      } catch {
        /* cropper coordinate API may vary */
      }
    }
    handleChange();
  }, [initialPixelRect, handleChange]);

  return (
    <div className="image-cropper">
      <Cropper
        ref={cropperRef}
        src={typeof imageSrc === 'string' ? imageSrc : ''}
        onChange={handleChange}
        onReady={handleReady}
        className="advanced-cropper-container"
        stencilProps={{ aspectRatio: undefined }}
      />
      {showCroppedPreview && croppedPreviewUrl && (
        <div className="crop-preview-wrap">
          <p className="edit-reid-hint">Cropped result:</p>
          <img src={croppedPreviewUrl} alt="Cropped" className="crop-preview-img" />
        </div>
      )}
      <div className="crop-actions">
        {commitMode === 'manual' && !hideApplyButton && (
          <button type="button" className="btn-primary" onClick={() => applyCrop(true)}>
            Apply crop
          </button>
        )}
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
});
