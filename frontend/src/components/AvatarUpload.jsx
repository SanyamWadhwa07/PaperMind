import { useState, useRef } from 'react';
import { useToast } from '../contexts/ToastContext';
import { Camera, X, User } from 'lucide-react';
import { profile } from '../lib/api';
import { Spinner } from './ui/primitives';

export default function AvatarUpload({ currentAvatar, onAvatarUpdate }) {
  const toast = useToast();
  const fileInputRef = useRef(null);

  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState(currentAvatar || null);

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      toast.error('Please select an image file');
      return;
    }

    // Validate file size (max 5MB)
    if (file.size > 5 * 1024 * 1024) {
      toast.error('Image must be less than 5MB');
      return;
    }

    // Show preview
    const reader = new FileReader();
    reader.onloadend = () => {
      setPreview(reader.result);
    };
    reader.readAsDataURL(file);

    // Upload file
    uploadAvatar(file);
  };

  const uploadAvatar = async (file) => {
    setUploading(true);

    try {
      const data = await profile.uploadAvatar(file);
      toast.success('Avatar updated');
      setPreview(data.avatar_url);
      onAvatarUpdate?.(data.avatar_url);
    } catch (error) {
      toast.error(error.message || 'Could not upload the avatar');
      setPreview(currentAvatar);
    } finally {
      setUploading(false);
    }
  };

  const deleteAvatar = async () => {
    if (!confirm('Are you sure you want to remove your avatar?')) return;

    try {
      await profile.removeAvatar();
      toast.success('Avatar removed');
      setPreview(null);
      onAvatarUpdate?.(null);
    } catch (error) {
      toast.error(error.message || 'Could not remove the avatar');
    }
  };

  return (
    <div className="relative shrink-0">
      <div className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-full border border-line bg-surface-sunk">
        {preview ? (
          <img src={preview} alt="" className="h-full w-full object-cover" />
        ) : (
          <User className="h-8 w-8 text-ink-faint" aria-hidden="true" />
        )}
      </div>

      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={uploading}
        className="absolute -bottom-1 -right-1 flex h-8 w-8 items-center justify-center rounded-full border border-line bg-surface text-ink-muted transition-colors duration-fast ease-out hover:border-line-strong hover:text-ink disabled:opacity-50"
        aria-label="Upload a new avatar"
        title="Upload avatar"
      >
        {uploading ? <Spinner size="sm" /> : <Camera className="h-4 w-4" />}
      </button>

      {preview && !uploading && (
        <button
          type="button"
          onClick={deleteAvatar}
          className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border border-line bg-surface text-ink-faint transition-colors duration-fast ease-out hover:border-danger/50 hover:text-danger"
          aria-label="Remove avatar"
          title="Remove avatar"
        >
          <X className="h-3 w-3" />
        </button>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleFileSelect}
        className="sr-only"
      />
    </div>
  );
}
