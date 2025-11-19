# Authentication & Database Setup Guide

## 🎯 **Overview**
Complete authentication system with user login, signup, profile management, and dashboard to track past summarizations.

## 📊 **Database Choice: Supabase (PostgreSQL)**

### Why Supabase?
- ✅ **Free Tier**: 500MB database, unlimited API requests
- ✅ **Built-in Auth**: Ready-to-use authentication system
- ✅ **Real-time**: WebSocket support for live updates
- ✅ **PostgreSQL**: Full-featured relational database
- ✅ **Auto APIs**: Instant REST & GraphQL APIs
- ✅ **Storage**: Free 1GB file storage included
- ✅ **Easy Setup**: No credit card required

---

## 🚀 **Step-by-Step Setup**

### **1. Create Supabase Account**

1. Go to [https://supabase.com](https://supabase.com)
2. Click "Start your project" → Sign up (free)
3. Create a new project:
   - Project name: `research-summarizer`
   - Database password: `<strong-password>` (save this!)
   - Region: Choose closest to you
   - Click "Create new project" (takes ~2 minutes)

### **2. Get Your Credentials**

Once project is created:

1. Go to **Settings** → **API**
2. Copy these values:
   ```
   Project URL: https://xxxxx.supabase.co
   anon public key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   service_role key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```

### **3. Create Database Tables**

1. Go to **SQL Editor** in Supabase dashboard
2. Copy the entire contents of `backend/database/schema.sql`
3. Paste into SQL Editor
4. Click "Run" (bottom right)
5. Verify tables created: Go to **Table Editor** → You should see:
   - `users`
   - `summaries`
   - `user_activity`
   - `user_summary_stats` (view)

### **4. Configure Backend**

1. Navigate to backend folder:
   ```powershell
   cd backend
   ```

2. Create `.env` file from template:
   ```powershell
   Copy-Item .env.example .env
   ```

3. Edit `.env` and add your Supabase credentials:
   ```env
   SUPABASE_URL=https://xxxxx.supabase.co
   SUPABASE_ANON_KEY=your-anon-key-from-step-2
   SUPABASE_SERVICE_KEY=your-service-role-key-from-step-2
   JWT_SECRET_KEY=your-random-secret-key-here
   ```

4. Generate a secure JWT secret:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Copy the output and use it for `JWT_SECRET_KEY`

### **5. Install Required Python Packages**

Add these to `backend/requirements.txt`:
```
supabase>=2.0.0
python-dotenv>=1.0.0
PyJWT>=2.8.0
bcrypt>=4.1.0
```

Install:
```powershell
pip install supabase python-dotenv PyJWT bcrypt
```

### **6. Test Backend**

1. Start Flask server:
   ```powershell
   cd backend
   python app.py
   ```

2. Test auth endpoint:
   ```powershell
   curl http://localhost:5000/api/auth/signup -X POST -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"Test123!","full_name":"Test User"}'
   ```

   Should return:
   ```json
   {
     "message": "User created successfully",
     "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
     "user": {...}
   }
   ```

### **7. Test Frontend**

1. Start React dev server:
   ```powershell
   cd frontend
   npm run dev
   ```

2. Open browser: `http://localhost:3000`
3. Click "Sign Up" → Create account
4. Should redirect to Dashboard

---

## 🔐 **Features Implemented**

### **Authentication**
- ✅ User Signup with validation
- ✅ User Login with JWT tokens
- ✅ Password hashing (bcrypt)
- ✅ Protected routes (require login)
- ✅ Auto-redirect to login if not authenticated

### **User Profile**
- ✅ View profile information
- ✅ Edit full name, bio
- ✅ View account statistics
- ✅ Member since date

### **Dashboard**
- ✅ View all past summaries
- ✅ Search summaries by title/arXiv ID
- ✅ Sort by date, title, processing time
- ✅ Delete summaries
- ✅ Statistics cards:
  - Total summaries
  - Avg processing time
  - Words processed
  - Active days
- ✅ Pagination for large datasets

### **Navigation**
- ✅ Responsive mobile menu
- ✅ Profile dropdown (desktop)
- ✅ Login/Logout buttons
- ✅ Dashboard link (authenticated users only)

---

## 📂 **File Structure**

```
backend/
├── database/
│   ├── schema.sql           # PostgreSQL database schema
│   └── config.py            # Supabase configuration
├── auth/
│   ├── utils.py             # JWT & password utilities
│   └── routes.py            # Auth endpoints (signup, login, profile)
├── routes/
│   └── summaries.py         # User summaries endpoints
├── .env                     # Environment variables (create from .env.example)
├── .env.example             # Template for environment variables
└── app.py                   # Main Flask app (updated with auth routes)

frontend/
├── src/
│   ├── contexts/
│   │   └── AuthContext.jsx  # Authentication state management
│   ├── components/
│   │   ├── Layout.jsx       # Updated with profile menu
│   │   └── ProtectedRoute.jsx # Route protection wrapper
│   ├── pages/
│   │   ├── LoginPage.jsx    # Login form
│   │   ├── SignupPage.jsx   # Signup form
│   │   ├── DashboardPage.jsx # User dashboard
│   │   └── ProfilePage.jsx  # User profile
│   └── App.jsx              # Updated with new routes
```

---

## 🔄 **API Endpoints**

### **Authentication**
```
POST   /api/auth/signup          # Create new user
POST   /api/auth/login           # Login user
GET    /api/auth/me              # Get current user (protected)
PUT    /api/auth/me              # Update profile (protected)
POST   /api/auth/change-password # Change password (protected)
```

### **Summaries (Protected)**
```
GET    /api/summaries            # Get user's summaries (paginated)
GET    /api/summaries/:id        # Get specific summary
POST   /api/summaries            # Create new summary
DELETE /api/summaries/:id        # Delete summary
GET    /api/dashboard/stats      # Get dashboard statistics
```

---

## 🧪 **Testing the System**

### **1. Create User Account**
```bash
# Signup
curl -X POST http://localhost:5000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!",
    "full_name": "John Doe"
  }'
```

### **2. Login**
```bash
# Login
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!"
  }'

# Returns: { "token": "eyJhbGciOi...", "user": {...} }
```

### **3. Get Profile (with token)**
```bash
curl http://localhost:5000/api/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

### **4. Create Summary**
```bash
curl -X POST http://localhost:5000/api/summaries \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "paper_title": "Test Paper",
    "paper_authors": ["Author 1"],
    "arxiv_id": "2511.12345",
    "summary_data": {...}
  }'
```

---

## 🛡️ **Security Features**

- ✅ **Password Hashing**: bcrypt with salt
- ✅ **JWT Tokens**: Secure 24-hour tokens
- ✅ **Password Requirements**: 
  - Minimum 8 characters
  - Uppercase + lowercase + number
- ✅ **Email Validation**: Regex pattern matching
- ✅ **Row Level Security (RLS)**: Users can only see their own data
- ✅ **HTTPS Ready**: Works with SSL in production
- ✅ **CORS Configured**: Secure cross-origin requests

---

## 🎨 **UI Features**

### **Responsive Design**
- Mobile hamburger menu
- Touch-friendly buttons (44px min)
- Responsive grids (1/2/4 columns)
- Horizontal scroll tabs on mobile

### **Dark Mode**
- System-wide dark/light mode toggle
- Persisted in localStorage
- Smooth transitions

### **Accessibility**
- ARIA labels
- Keyboard navigation
- Focus states
- Screen reader friendly

---

## 🚨 **Troubleshooting**

### **Issue: "Module not found: supabase"**
```powershell
pip install supabase python-dotenv PyJWT bcrypt
```

### **Issue: "Token has expired"**
- Tokens expire after 24 hours
- User needs to login again
- Frontend automatically redirects to /login

### **Issue: "User not found"**
- Check Supabase dashboard → Table Editor → users table
- Verify user was created successfully
- Check email spelling

### **Issue: "CORS error"**
- Ensure Flask app has `CORS(app)` enabled
- Check frontend is calling `http://localhost:5000`
- Verify backend is running

### **Issue: "Database connection failed"**
- Verify `.env` file exists in `backend/` folder
- Check SUPABASE_URL and keys are correct
- Test connection in Supabase dashboard

---

## 📊 **Database Schema Overview**

### **users** table
- `id` (UUID, Primary Key)
- `email` (Unique, Required)
- `password_hash` (bcrypt)
- `full_name`
- `bio`
- `avatar_url`
- `created_at`, `updated_at`, `last_login`
- `is_active` (Boolean)

### **summaries** table
- `id` (UUID, Primary Key)
- `user_id` (Foreign Key → users)
- `paper_title`, `paper_authors`, `paper_url`, `arxiv_id`
- `summary_data` (JSONB - flexible summary content)
- `model_used`, `processing_time_seconds`, `word_count`
- `created_at`, `updated_at`
- `search_vector` (Full-text search)

### **user_activity** table
- Track user actions (search, summarize, export, view)
- Useful for analytics

---

## 🎯 **Next Steps**

1. ✅ **Setup Complete** - Test signup/login
2. 🔄 **Modify Summarization** - Save summaries to database instead of JSON files
3. 📊 **Analytics** - Add charts to dashboard (Chart.js or Recharts)
4. 🔔 **Notifications** - Toast messages for success/error
5. 📧 **Email Verification** - Use Supabase Auth Email templates
6. 🔄 **Password Reset** - Forgot password functionality
7. 🎨 **Avatar Upload** - Use Supabase Storage for profile pictures
8. 🌐 **Deploy** - Deploy to Vercel (frontend) + Render (backend)

---

## 💡 **Pro Tips**

1. **Free Supabase Limits**:
   - 500MB database
   - 1GB file storage
   - 2GB bandwidth/month
   - 50,000 monthly active users
   - Perfect for MVP and testing!

2. **Development Workflow**:
   - Use Supabase dashboard to inspect data
   - Enable RLS policies in production
   - Use `.env.local` for local overrides

3. **Production Checklist**:
   - Change JWT_SECRET_KEY
   - Enable RLS policies
   - Use HTTPS only
   - Set strong CORS rules
   - Enable rate limiting

---

## 📞 **Support**

- **Supabase Docs**: https://supabase.com/docs
- **Supabase Discord**: https://discord.supabase.com
- **PostgreSQL Docs**: https://www.postgresql.org/docs/

---

**You now have a complete authentication system with user profiles and dashboard! 🎉**
