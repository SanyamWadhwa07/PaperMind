# 🧠 PaperMind - AI Research Paper Summarizer

<div align="center">
  
  ![PaperMind Logo](https://img.shields.io/badge/PaperMind-AI%20Research%20Assistant-00988F?style=for-the-badge&logo=brain&logoColor=white)
  
  **Transform complex research papers into clear, actionable insights with AI**
  
  [![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org/)
  [![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
  [![PyTorch](https://img.shields.io/badge/PyTorch-2.0-EE4C2C?style=flat&logo=pytorch&logoColor=white)](https://pytorch.org/)
  [![Supabase](https://img.shields.io/badge/Supabase-Database-3ECF8E?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)
  
</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Demo](#-demo)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Documentation](#-documentation)
- [Usage Examples](#-usage-examples)
- [API Reference](#-api-reference)
- [Deployment](#-deployment)
- [Troubleshooting](#-troubleshooting)
- [FAQ](#-faq)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🌟 Overview

**PaperMind** is an advanced AI-powered research paper summarization platform that helps researchers, students, and professionals quickly understand complex academic papers. Using state-of-the-art NLP models and a parallel multi-agent architecture, PaperMind delivers comprehensive analysis including:

- 📝 **Hierarchical Summaries** - From high-level overviews to detailed section breakdowns
- 🔍 **Entity Extraction** - Automatic identification of models, datasets, metrics, and frameworks
- 📊 **Quantitative Results** - Extraction of experimental results and performance metrics
- 🖼️ **Figure Analysis** - Smart extraction and ranking of important figures
- 🌐 **Methodology Flowcharts** - Visual representation of research methodologies
- 🔑 **Keyword Analysis** - KeyBERT-powered keyword extraction with context

### Why PaperMind?

- **Save Time**: Read a 20-page paper in 2 minutes
- **Deep Understanding**: Multi-level summaries (simple, detailed, ELI5, technical)
- **Smart Organization**: Store and track all your research in one place
- **Collaborative**: Share summaries and insights with your team
- **Always Learning**: Cross-paper learning improves summaries over time

---

## 🎯 Key Features

### 🧠 **AI-Powered Summarization**
- **LED Transformer** with 16,384 token context window
- **Parallel Multi-Agent System** for 2.5x faster processing
- **Multiple Summary Types**: Simple, Detailed, ELI5, Technical
- **Cross-Paper Learning**: Experience-based improvements via Supabase

### ⚡ **Lightning Fast Processing**
- Process papers in 10-30 seconds with GPU acceleration
- Async batch processing for multiple papers
- Real-time progress tracking
- Smart caching and optimization

### 🔐 **Enterprise-Grade Security**
- Full authentication system with JWT tokens
- Email verification for new accounts
- Password reset with secure tokens
- Role-based access control (coming soon)

### 📊 **Advanced Analytics**
- Interactive activity charts (Chart.js)
- Entity extraction (SciBERT)
- Keyword analysis (KeyBERT)
- Quantitative results extraction from tables and text
- Methodology flowcharts (Mermaid.js)

### 🎨 **Beautiful User Experience**
- Modern, responsive design with Tailwind CSS
- Dark mode support
- Real-time toast notifications
- Drag-and-drop file upload
- Mobile-optimized interface

### 💾 **Comprehensive Storage**
- PostgreSQL database via Supabase
- Avatar uploads to Supabase Storage
- Export summaries to JSON/Markdown
- Full-text search capabilities


---

## 🚀 Quick Start

### Prerequisites

- **Python** 3.8 or higher
- **Node.js** 16 or higher
- **GPU with CUDA** (optional, for faster processing)
- **Supabase Account** ([Sign up free](https://supabase.com))

### Installation

#### 1️⃣ Clone the Repository

```bash
git clone https://github.com/SanyamWadhwa07/PaperMind.git
cd PaperMind
```

#### 2️⃣ Backend Setup

```powershell
# Create and activate virtual environment
python -m venv research
.\research\Scripts\Activate.ps1

# Navigate to backend
cd backend

# Install Python dependencies
pip install -r requirements.txt

# Create .env file
New-Item -Path .env -ItemType File
```

Add to `backend/.env`:
```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
JWT_SECRET_KEY=your_random_secret_key_here
```

#### 3️⃣ Frontend Setup

```powershell
# Navigate to frontend
cd ..\frontend

# Install Node dependencies
npm install
```

#### 4️⃣ Database Setup

1. Create a new project at [Supabase](https://supabase.com)
2. Go to SQL Editor
3. Run the schema from `backend/database/schema.sql`
4. Update your `.env` file with credentials

#### 5️⃣ Run the Application

**Terminal 1 - Backend (Flask API)**
```powershell
cd backend
python app.py
```
Backend runs on `http://localhost:5000`

**Terminal 2 - Frontend (React)**
```powershell
cd frontend
npm run dev
```
Frontend runs on `http://localhost:5173`

🎉 **Open your browser and visit `http://localhost:5173`!**

---

## 📁 Project Structure

```
PaperMind/
├── 📂 backend/                  # Flask REST API
│   ├── app.py                   # Main Flask application
│   ├── requirements.txt         # Python dependencies
│   ├── auth/                    # Authentication modules
│   │   ├── routes.py           # Auth endpoints
│   │   ├── supabase_auth.py    # Supabase integration
│   │   └── utils.py            # Auth utilities
│   ├── database/               # Database configuration
│   │   ├── schema.sql          # PostgreSQL schema
│   │   ├── config.py           # Supabase config
│   │   └── experience_schema.sql
│   ├── routes/                 # API route blueprints
│   │   ├── summaries.py        # Summary CRUD operations
│   │   ├── process_paper.py    # Paper processing
│   │   └── profile.py          # User profile management
│   ├── uploads/                # Uploaded PDF files
│   └── summaries_api/          # Generated summaries
│
├── 📂 frontend/                 # React application
│   ├── package.json            # Node dependencies
│   ├── vite.config.js          # Vite configuration
│   ├── tailwind.config.js      # Tailwind CSS config
│   ├── index.html              # HTML entry point
│   └── src/
│       ├── components/         # Reusable UI components
│       ├── pages/              # Page components
│       ├── contexts/           # React contexts
│       ├── api.js              # API client
│       └── App.jsx             # Root component
│
├── 📂 core/                     # AI/ML Core Engine
│   ├── agent_integration.py    # Multi-agent orchestration
│   ├── agents/                 # Specialized AI agents
│   │   ├── orchestrator.py    # Agent coordinator
│   │   ├── summary_agent.py   # Summarization agent
│   │   ├── entity_agent.py    # Entity extraction
│   │   ├── figure_agent.py    # Figure analysis
│   │   └── reasoning_agent.py # Reasoning tasks
│   ├── llm/                    # LLM integrations
│   └── memory/                 # Memory management
│
├── 📂 docs/                     # Documentation
│   ├── QUICKSTART.md
│   ├── COMPLETE_DOCUMENTATION.md
│   ├── AGENT_SYSTEM_README.md
│   ├── AUTH_SETUP.md
│   └── OLLAMA_SETUP.md
│
├── 📂 setups/                   # Setup scripts
│   ├── setup.ps1               # Main setup script
│   ├── setup_ollama.ps1        # Ollama installation
│   └── setup_supabase_experience.ps1
│
├── main.py                      # CLI summarization tool
├── requirements.txt             # Root Python dependencies
├── patterns.json                # Entity extraction patterns
├── config.example.yaml          # Configuration template
├── .gitignore                   # Git ignore rules
└── README.md                    # This file
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend Layer                        │
│  React 18 + Vite + Tailwind CSS + Chart.js + Router        │
└────────────────────┬────────────────────────────────────────┘
                     │ REST API (axios)
┌────────────────────▼────────────────────────────────────────┐
│                        Backend Layer                         │
│         Flask 3.0 + Flask-CORS + JWT + Blueprints           │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │   Auth     │  │  Summaries │  │  Process   │            │
│  │  Routes    │  │   Routes   │  │   Paper    │            │
│  └────────────┘  └────────────┘  └────────────┘            │
└────────────────────┬───────────────┬────────────────────────┘
                     │               │
        ┌────────────▼─────┐   ┌────▼──────────────────┐
        │   Supabase DB    │   │   AI/ML Core Engine   │
        │   PostgreSQL     │   │   Multi-Agent System  │
        │   + Storage      │   │   LED + SciBERT       │
        └──────────────────┘   └───────────────────────┘
```

### Multi-Agent Architecture

PaperMind uses a **parallel multi-agent system** for efficient paper analysis:

```
┌─────────────────┐
│   Orchestrator  │  (Coordinates all agents)
└────────┬────────┘
         │
    ┌────┴────┬────────┬─────────┬─────────┐
    ▼         ▼        ▼         ▼         ▼
┌────────┐ ┌──────┐ ┌──────┐ ┌───────┐ ┌──────┐
│Summary │ │Entity│ │Figure│ │Results│ │Reason│
│ Agent  │ │Agent │ │Agent │ │ Agent │ │Agent │
└────────┘ └──────┘ └──────┘ └───────┘ └──────┘
```

**Benefits:**
- 2.5x faster than sequential processing
- Parallel execution of independent tasks
- Modular and maintainable codebase
- Easy to extend with new agents

---

## 🛠️ Tech Stack

### Frontend Technologies
| Technology | Purpose | Version |
|------------|---------|---------|
| **React** | UI Framework | 18.2.0 |
| **Vite** | Build Tool | 5.0.8 |
| **Tailwind CSS** | Styling | 3.3.6 |
| **React Router** | Navigation | 6.20.0 |
| **Chart.js** | Data Visualization | 4.5.1 |
| **Axios** | HTTP Client | 1.6.2 |
| **React Toastify** | Notifications | 11.0.5 |
| **Lucide React** | Icons | 0.294.0 |
| **Mermaid** | Flowcharts | 10.6.1 |

### Backend Technologies
| Technology | Purpose | Version |
|------------|---------|---------|
| **Flask** | Web Framework | 3.0.0 |
| **Flask-CORS** | CORS Support | 4.0.0 |
| **Supabase** | Database & Auth | 2.0+ |
| **PyJWT** | JWT Tokens | 2.8.0 |
| **bcrypt** | Password Hashing | 4.1.0 |

### AI/ML Technologies
| Technology | Purpose | Version |
|------------|---------|---------|
| **PyTorch** | Deep Learning | 2.0+ |
| **Transformers** | NLP Models | 4.30+ |
| **LED** | Long Document Summarization | - |
| **SciBERT** | Scientific Entity Extraction | - |
| **KeyBERT** | Keyword Extraction | 0.8.0 |
| **NLTK** | Text Processing | 3.8.1 |
| **PyMuPDF** | PDF Parsing | 1.23+ |
| **pdfplumber** | Table Extraction | 0.10+ |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[QUICKSTART.md](docs/QUICKSTART.md)** | Fast 5-minute setup guide |
| **[COMPLETE_DOCUMENTATION.md](docs/COMPLETE_DOCUMENTATION.md)** | Comprehensive system documentation |
| **[AGENT_SYSTEM_README.md](docs/AGENT_SYSTEM_README.md)** | Multi-agent architecture details |
| **[AUTH_SETUP.md](docs/AUTH_SETUP.md)** | Authentication system guide |
| **[OLLAMA_SETUP.md](docs/OLLAMA_SETUP.md)** | Local LLM setup instructions |
| **[API_RESPONSE_SCHEMA.md](backend/API_RESPONSE_SCHEMA.md)** | API response formats |

---

## 💡 Usage Examples

### 1. Summarize from arXiv

```python
# Using the CLI
python main.py --query "cat:cs.LG" --max-results 5

# Using the API
import requests

response = requests.post('http://localhost:5000/api/search', json={
    'query': 'cat:cs.CV AND ti:transformer',
    'max_results': 3
})
papers = response.json()['papers']
```

### 2. Upload and Process PDF

```python
# Using the API
files = {'file': open('paper.pdf', 'rb')}
upload_response = requests.post('http://localhost:5000/api/upload', files=files)
file_id = upload_response.json()['file_id']

# Summarize uploaded paper
summary_response = requests.post('http://localhost:5000/api/summarize', json={
    'pdf_path': upload_response.json()['filepath'],
    'title': 'My Research Paper'
})
```

### 3. Batch Processing

```python
# Process multiple papers
papers = [
    {'pdf_path': 'paper1.pdf', 'title': 'Paper 1'},
    {'pdf_path': 'paper2.pdf', 'title': 'Paper 2'},
]

response = requests.post('http://localhost:5000/api/batch/summarize', json={
    'papers': papers
})
results = response.json()['results']
```

### 4. Export Summary

```python
# Export as Markdown
response = requests.get(
    f'http://localhost:5000/api/export/{summary_id}',
    params={'format': 'markdown'}
)
# Downloads summary.md file
```

---

## 🔌 API Reference

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register` | Register new user |
| `POST` | `/api/auth/login` | Login user |
| `POST` | `/api/auth/reset-password` | Request password reset |
| `POST` | `/api/auth/update-password` | Update password |
| `GET` | `/api/auth/me` | Get current user |

### Paper Processing Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/search` | Search arXiv papers |
| `POST` | `/api/upload` | Upload PDF file |
| `POST` | `/api/summarize` | Summarize paper (sync) |
| `POST` | `/api/summarize/async` | Summarize paper (async) |
| `GET` | `/api/status/:task_id` | Check async task status |

### Summary Management Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/summaries` | List all summaries |
| `GET` | `/api/summary/:id` | Get specific summary |
| `DELETE` | `/api/summary/:id` | Delete summary |
| `GET` | `/api/export/:id` | Export summary |

### User Profile Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/profile` | Get user profile |
| `PUT` | `/api/profile` | Update profile |
| `POST` | `/api/profile/avatar` | Upload avatar |

For detailed API documentation, see [API_RESPONSE_SCHEMA.md](backend/API_RESPONSE_SCHEMA.md).

---

## 🚀 Deployment

### Frontend Deployment (Vercel/Netlify)

**Option 1: Vercel**
```bash
# Install Vercel CLI
npm i -g vercel

# Deploy from frontend directory
cd frontend
vercel
```

**Option 2: Netlify**
```bash
# Build the frontend
cd frontend
npm run build

# Deploy dist/ folder to Netlify
# Or connect your GitHub repo to Netlify for automatic deployments
```

### Backend Deployment (Railway/Render/Heroku)

**Option 1: Railway**
1. Create account at [Railway](https://railway.app)
2. New Project → Deploy from GitHub
3. Add environment variables from `.env`
4. Railway will auto-detect Flask and deploy

**Option 2: Render**
1. Create account at [Render](https://render.com)
2. New Web Service → Connect repository
3. Build Command: `pip install -r backend/requirements.txt`
4. Start Command: `cd backend && python app.py`
5. Add environment variables

### Environment Variables for Production

```env
# Backend .env
SUPABASE_URL=your_production_supabase_url
SUPABASE_KEY=your_production_supabase_key
JWT_SECRET_KEY=your_strong_random_secret
FLASK_ENV=production
FRONTEND_URL=https://your-frontend-domain.com

# Frontend .env
VITE_API_URL=https://your-backend-domain.com
VITE_SUPABASE_URL=your_production_supabase_url
VITE_SUPABASE_ANON_KEY=your_production_supabase_key
```

### Database Migration

```bash
# Export from local Supabase (if needed)
supabase db dump > backup.sql

# Import to production Supabase
psql -h your-db.supabase.co -U postgres -d postgres < backend/database/schema.sql
```

---

## 🔧 Troubleshooting

### Common Issues

#### 1. **ModuleNotFoundError: No module named 'transformers'**
```powershell
# Ensure you're in the virtual environment
.\research\Scripts\Activate.ps1

# Reinstall dependencies
pip install -r requirements.txt
```

#### 2. **CUDA Out of Memory**
```python
# Use lightweight mode
python main.py --lightweight --no-ocr

# Or use CPU only
python main.py --device cpu
```

#### 3. **Supabase Connection Error**
```powershell
# Check your .env file exists
ls backend\.env

# Verify credentials are correct
echo $env:SUPABASE_URL  # Should show your URL
```

#### 4. **React App Not Loading**
```powershell
# Clear cache and reinstall
cd frontend
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json
npm install
npm run dev
```

#### 5. **Port Already in Use**
```powershell
# Find process using port 5000
netstat -ano | findstr :5000

# Kill the process (replace PID with actual process ID)
Stop-Process -Id PID -Force

# Or use different port
set FLASK_RUN_PORT=5001
python app.py
```

#### 6. **PDF Upload Fails**
- Check file size < 50MB
- Ensure `uploads/` directory exists
- Verify correct file permissions

```powershell
# Create uploads directory if missing
New-Item -ItemType Directory -Path backend\uploads -Force
```

### Performance Optimization

**For Better GPU Utilization:**
```python
# Check GPU availability
python -c "import torch; print(torch.cuda.is_available())"

# Monitor GPU usage
nvidia-smi -l 1
```

**For Faster Summarization:**
- Use `--lightweight` mode for quick tests
- Enable GPU acceleration if available
- Reduce `--max-figures` and `--max-entities`
- Use `config.yaml` for persistent settings

---

## ❓ FAQ

### General Questions

**Q: Is PaperMind free to use?**  
A: Yes! PaperMind is open-source and free. You only pay for your own infrastructure (Supabase free tier is sufficient for personal use).

**Q: Do I need a GPU to run PaperMind?**  
A: No, but it's recommended. CPU mode works but is slower (2-5 minutes per paper vs 10-30 seconds with GPU).

**Q: What paper formats are supported?**  
A: Currently PDF and arXiv papers. Support for Word docs, HTML, and LaTeX coming soon.

**Q: Can I run this locally without internet?**  
A: Partially. You need internet for arXiv downloads and Supabase. For fully offline mode, use local LLM (Ollama) and SQLite database.

**Q: How accurate are the summaries?**  
A: Entity extraction is ~95% accurate. Summary quality depends on paper complexity. We use LED (state-of-the-art for long documents) with 16K context.

### Technical Questions

**Q: Can I use a different database instead of Supabase?**  
A: Yes! You can modify `backend/database/config.py` to use PostgreSQL, MySQL, or SQLite.

**Q: How do I add custom summary types?**  
A: Edit `config.yaml` under `summary_config` section and update the agent system in `core/agents/`.

**Q: Can I integrate with other LLMs (GPT-4, Claude)?**  
A: Yes! Update `core/llm/` with your LLM client. Currently supports Ollama and HuggingFace models.

**Q: What's the maximum paper length?**  
A: LED supports up to 16,384 tokens (~50-60 pages). Longer papers are chunked and summarized hierarchically.

**Q: Can I batch process hundreds of papers?**  
A: Yes! Use the `/api/batch/summarize` endpoint. For large batches, consider using background workers (Celery/RQ).

### Deployment Questions

**Q: Where should I deploy this?**  
A: Frontend: Vercel/Netlify. Backend: Railway/Render/Heroku. Database: Supabase (managed PostgreSQL).

**Q: What are the hosting costs?**  
A: Free tier options available:
- Supabase: Free (500MB database, 1GB storage)
- Vercel: Free (100GB bandwidth)
- Railway: $5/month (500 hours)

**Q: Can I self-host everything?**  
A: Absolutely! Deploy on your own VPS with Docker (Dockerfile coming soon).

---

## 📊 Performance Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| **Context Window** | 16,384 tokens | LED model capacity |
| **Compression Ratio** | 70-80% | Summary vs original |
| **Processing Time** | 10-30s | With GPU acceleration |
| **Speedup (Agents)** | 2.5x | vs sequential |
| **Max File Size** | 50 MB | PDF upload limit |
| **GPU Memory** | 3-4 GB | RTX 2050/3050 |
| **Accuracy** | ~95% | Entity extraction |
| **Supported Formats** | PDF, arXiv | More coming soon |

---

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### Ways to Contribute
- 🐛 Report bugs and issues
- 💡 Suggest new features
- 📝 Improve documentation
- 🔧 Submit pull requests
- ⭐ Star the repository

### Development Setup

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (coming soon)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Style
- **Python**: Follow PEP 8
- **JavaScript/React**: Use ESLint configuration
- **Commits**: Use conventional commits (feat, fix, docs, etc.)

### Reporting Issues

When reporting issues, please include:
- Python version (`python --version`)
- Node version (`node --version`)
- Operating system
- Error messages and stack traces
- Steps to reproduce

### Feature Requests

We're always looking for ideas! Submit feature requests via [GitHub Issues](https://github.com/SanyamWadhwa07/PaperMind/issues) with the `enhancement` label.

---

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Hugging Face** for the amazing Transformers library
- **Supabase** for the awesome backend platform
- **arXiv** for providing free access to research papers
- **React** and **Vite** communities for excellent tooling
- All contributors and users who provide feedback

---

## 📧 Contact & Support

- **Author**: Sanyam Wadhwa
- **GitHub**: [@SanyamWadhwa07](https://github.com/SanyamWadhwa07)
- **Issues**: [GitHub Issues](https://github.com/SanyamWadhwa07/PaperMind/issues)

### Get Help
- 📖 Check the [Documentation](docs/)
- 🐛 Report bugs via [Issues](https://github.com/SanyamWadhwa07/PaperMind/issues)
- 💬 Ask questions in [Discussions](https://github.com/SanyamWadhwa07/PaperMind/discussions)

---

## ⭐ Show Your Support

If you find PaperMind useful, please consider:
- ⭐ Starring the repository
- 🐦 Sharing on social media
- 📝 Writing a blog post about your experience
- 💰 Sponsoring the project (coming soon)

---

<div align="center">

**Made with ❤️ by researchers, for researchers**

[⬆ Back to Top](#-papermind---ai-research-paper-summarizer)

</div>
