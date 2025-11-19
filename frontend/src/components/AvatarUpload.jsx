import { useState, useRef } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { Camera, Upload, X, User } from 'lucide-react';

export default function AvatarUpload({ currentAvatar, onAvatarUpdate }) {
  const { token, user } = useAuth();
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
      const formData = new FormData();
      formData.append('avatar', file);

      const response = await fetch('http://localhost:5000/api/profile/avatar', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        },
        body: formData
      });

      const data = await response.json();

      if (response.ok) {
        toast.success('Avatar uploaded successfully!');
        setPreview(data.avatar_url);
        if (onAvatarUpdate) {
          onAvatarUpdate(data.avatar_url);
        }
      } else {
        toast.error(data.error || 'Failed to upload avatar');
        setPreview(currentAvatar);
      }
    } catch (error) {
      console.error('Upload error:', error);
      toast.error('Failed to upload avatar');
      setPreview(currentAvatar);
    }

    setUploading(false);
  };

  const deleteAvatar = async () => {
    if (!confirm('Are you sure you want to remove your avatar?')) return;

    try {
      const response = await fetch('http://localhost:5000/api/profile/avatar', {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        toast.success('Avatar removed');
        setPreview(null);
        if (onAvatarUpdate) {
          onAvatarUpdate(null);
        }
      } else {
        toast.error('Failed to remove avatar');
      }
    } catch (error) {
      toast.error('Failed to remove avatar');
    }
  };

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative">
        {/* Avatar Display */}
        <div className="w-32 h-32 rounded-full bg-slate-700 border-4 border-slate-600 overflow-hidden flex items-center justify-center">
          {preview ? (
            <img 
              src={preview} 
              alt="Avatar" 
              className="w-full h-full object-cover"
            />
          ) : (
            <User className="w-16 h-16 text-slate-400" />
          )}
        </div>

        {/* Upload Button Overlay */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="absolute bottom-0 right-0 bg-teal-500 hover:bg-teal-600 text-white p-2 rounded-full shadow-lg transition-colors disabled:opacity-50"
          title="Upload avatar"
        >
          {uploading ? (
            <div className="animate-spin rounded-full h-5 w-5 border-2 border-white border-t-transparent" />
          ) : (
            <Camera className="w-5 h-5" />
          )}
        </button>

        {/* Delete Button */}
        {preview && (
          <button
            onClick={deleteAvatar}
            className="absolute top-0 right-0 bg-red-500 hover:bg-red-600 text-white p-1.5 rounded-full shadow-lg transition-colors"
            title="Remove avatar"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleFileSelect}
        className="hidden"
      />

      {/* Upload Instructions */}
      <div className="text-center">
        <p className="text-sm text-slate-400">
          Click the camera icon to upload
        </p>
        <p className="text-xs text-slate-500 mt-1">
          JPG, PNG or GIF • Max 5MB
        </p>
      </div>
    </div>
  );
}
