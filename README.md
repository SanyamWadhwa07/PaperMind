# 🧠 PaperMind - AI Research Paper Summarizer

<div align="center">
  
  ![PaperMind Logo](https://img.shields.io/badge/PaperMind-AI%20Research%20Assistant-00988F?style=for-the-badge&logo=brain&logoColor=white)
  
  **Transform complex research papers into clear, actionable insights with AI**
  
  [![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org/)
  [![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
  [![Supabase](https://img.shields.io/badge/Supabase-Database-3ECF8E?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)
  [![License](https://img.shields.io/badge/License-Educational-blue.svg)](LICENSE)
  
</div>

---

## ✨ What is PaperMind?

**PaperMind** is an advanced AI-powered research paper summarization platform that helps researchers, students, and professionals quickly understand complex academic papers. Using cutting-edge NLP with the LED (Longformer Encoder-Decoder) transformer model, PaperMind performs hierarchical summarization that captures both high-level insights and detailed section-by-section breakdowns.

### 🎯 Key Features

- 🧠 **AI-Powered Summarization** - LED transformer with 16K context for deep understanding
- ⚡ **Lightning Fast** - Process papers in seconds with GPU acceleration
- 🔒 **Secure & Private** - Full authentication system with email verification
- 📊 **Smart Analytics** - Entity extraction, keyword analysis, flowcharts, and visualizations
- 📈 **Activity Dashboard** - Track your research progress with interactive charts
- 🎨 **Beautiful UI** - Modern, responsive design with dark mode support
- 💾 **Database Storage** - All summaries saved to Supabase PostgreSQL
- 🔔 **Toast Notifications** - Real-time feedback for all actions
- 👤 **User Profiles** - Avatar upload, password reset, activity tracking

---

## 🚀 Quick Start
---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+
- GPU with CUDA (optional, for faster processing)
- Supabase account (free tier available)

### Installation

1. **Clone or download the repository**

2. **Backend Setup**
```powershell
# Create virtual environment
python -m venv research
.\research\Scripts\Activate.ps1

# Install dependencies
cd backend
pip install -r requirements.txt

# Configure environment variables
# Create backend/.env with:
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
JWT_SECRET_KEY=your_secret_key
```

3. **Frontend Setup**
```powershell
cd frontend
npm install
```

4. **Database Setup**
- Create a Supabase project
- Run the SQL schema from `backend/database/schema.sql`
- Update `.env` with your credentials

### Running the Application

**Terminal 1 - Backend (Flask API):**
```powershell
cd backend
python app.py
# Runs on http://localhost:5000
```

**Terminal 2 - Frontend (React + Vite):**
```powershell
cd frontend
npm run dev
# Runs on http://localhost:5173
```

Visit `http://localhost:5173` and start summarizing papers!

---

## 📖 Documentation

```
research-paper-summarizer/
├── 📖 Documentation Files
│   ├── QUICKSTART.md              ⭐ Start here
│   ├── FULLSTACK_README.md        📘 Full documentation
│   ├── API_DOCUMENTATION.md       🔌 API reference
│   ├── ARCHITECTURE.md            🏗️ System design
│   ├── SETUP_COMPLETE.md          ✅ Setup summary
│   └── PROJECT_DOCUMENTATION.md   📝 Original docs
│
├── 🔧 Backend (Flask API)
│   ├── app.py                     🌐 API server
│   ├── requirements.txt           📦 Dependencies
│   └── [uploads/, summaries_api/] 📂 Data folders
│
├── 🎨 Frontend (React)
│   ├── src/
│   │   ├── components/           🧩 UI components
│   │   ├── pages/                📄 Route pages
│   │   └── api.js                🔌 API client
│   ├── package.json              📦 Dependencies
│   └── vite.config.js            ⚙️ Build config
│
├── 🤖 ML Core
│   ├── main.py                   🧠 Summarization engine
│   └── streamlit.py              📊 Streamlit UI
│
└── 🛠️ Setup
    ├── setup.ps1                 🚀 Auto setup
    ├── requirements.txt          📦 Python deps
    └── .gitignore                🚫 Git ignore
```

## ✨ Features at a Glance

### 🔍 Input Methods
- ✅ Upload PDF files (max 50MB)
- ✅ Search arXiv by category/author/title
- ✅ Batch processing support

### 🤖 AI Processing
- ✅ LED transformer (16K context)
- ✅ Hierarchical summarization
- ✅ Entity extraction (models, datasets, metrics)
- ✅ Keyword analysis
- ✅ Flowchart generation

### 📊 Output Formats
- ✅ Web interface (interactive)
- ✅ JSON export
- ✅ Markdown export
- ✅ Section-by-section summaries

### 🎨 User Experience
- ✅ Real-time progress tracking
- ✅ Responsive design (mobile-friendly)
- ✅ Interactive visualizations
- ✅ Mermaid flowcharts
- ✅ Entity badges
- ✅ Keyword clouds

## 🎓 Learning Path

### For Beginners
1. Read [QUICKSTART.md](QUICKSTART.md)
2. Run Streamlit version
3. Try the React version
4. Read [FULLSTACK_README.md](FULLSTACK_README.md)

### For Developers
1. Review [ARCHITECTURE.md](ARCHITECTURE.md)
2. Explore [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
3. Study code in `backend/` and `frontend/`
4. Customize and extend

### For ML Engineers
1. Review [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)
2. Study [main.py](main.py)
3. Understand model pipeline
4. Optimize for your use case

## 🔧 Common Tasks

### Run the Application
```powershell
# Streamlit
streamlit run streamlit.py

# React + Flask
cd backend && python app.py
cd frontend && npm run dev
```

### Install Dependencies
```powershell
# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### Test the API
```powershell
# Health check
curl http://localhost:5000/api/health

# Search papers
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"cat:cs.LG","max_results":5}'
```

### Export a Summary
```powershell
# Get summary as JSON
curl http://localhost:5000/api/summary/uuid-here

# Export as Markdown
curl http://localhost:5000/api/export/uuid-here?format=markdown
```

## 📊 Performance Metrics

| Metric | Value |
|--------|-------|
| Context Length | 16,384 tokens |
| Compression Ratio | 70-80% |
| Processing Time | 3-4 min/paper |
| Supported Formats | PDF only |
| Max File Size | 50 MB |
| GPU Memory | 3-4 GB |

## 🌟 Tech Stack

**Frontend:** React, Vite, Tailwind CSS, React Router, Axios  
**Backend:** Flask, Flask-CORS, Threading  
**AI/ML:** PyTorch, Transformers, LED, SciBERT, MiniLM  
**Utilities:** PyMuPDF, arXiv, NLTK, KeyBERT  

## 🎯 Use Cases

### Research
- Quickly understand new papers
- Extract key findings
- Identify relevant datasets and models
- Compare methodologies

### Education
- Study paper structure
- Learn summarization techniques
- Understand entity extraction
- Practice with real papers

### Development
- Learn full-stack development
- Practice API design
- Study React patterns
- Understand ML pipelines

## 🚨 Troubleshooting

### Quick Fixes
```powershell
# Backend won't start
pip install -r backend/requirements.txt

# Frontend won't start
cd frontend
rm -rf node_modules
npm install

# CUDA errors
# Edit main.py, set device = "cpu"

# Port conflicts
# Edit backend/app.py, change port
# Edit frontend/vite.config.js, change port
```

### Get Help
1. Check error messages in terminal
2. Review browser console (F12)
3. Verify all dependencies installed
4. Check documentation files
5. Review code comments

## 📈 Next Steps

### Immediate
1. ✅ Run setup script: `.\setup.ps1`
2. ✅ Start both servers
3. ✅ Upload a PDF and test
4. ✅ Explore all features

### Short-term
1. Customize UI colors and branding
2. Add authentication
3. Deploy to cloud
4. Add more export formats

### Long-term
1. Implement database storage
2. Add collaborative features
3. Create mobile app
4. Scale to handle more users

## 🤝 Contributing

Want to improve the project?

1. **Frontend:** Enhance UI/UX in `frontend/src/`
2. **Backend:** Add API endpoints in `backend/app.py`
3. **ML:** Improve models in `main.py`
4. **Docs:** Update documentation files

## 📝 License

Educational and research use only.

## 🙏 Credits

- **Allen AI** - LED and SciBERT models
- **Hugging Face** - Transformers library
- **arXiv** - Open access research papers
- **Community** - Open source contributors

---

## 🎉 You're All Set!

You now have:
- ✅ A working Streamlit app
- ✅ A professional React + Flask application
- ✅ Complete documentation
- ✅ RESTful API
- ✅ Modern UI/UX
- ✅ Production-ready codebase

**Start with [QUICKSTART.md](QUICKSTART.md) and begin summarizing papers!** 🚀

---

*Last updated: November 2025*  
*Optimized for RTX 2050 4GB*
