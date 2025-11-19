# Quick Start Guide

## Option 1: Streamlit (Original)

```powershell
# Activate environment
.\research\Scripts\Activate.ps1

# Run Streamlit app
streamlit run streamlit.py
```

Access at: http://localhost:8501

## Option 2: React + Flask (New Professional App)

### Terminal 1 - Backend
```powershell
# Activate environment
.\research\Scripts\Activate.ps1

# Start Flask API
cd backend
python app.py
```

### Terminal 2 - Frontend
```powershell
# Start React app
cd frontend
npm run dev
```

Access at: http://localhost:3000

## First Time Setup

### Backend Dependencies
```powershell
cd backend
pip install -r requirements.txt
```

### Frontend Dependencies
```powershell
cd frontend
npm install
```

## Features Comparison

| Feature | Streamlit | React + Flask |
|---------|-----------|---------------|
| UI Design | Simple | Professional |
| Performance | Good | Better |
| Customization | Limited | Full control |
| API Access | No | Yes (RESTful) |
| Mobile Support | Basic | Responsive |
| Async Processing | No | Yes |
| Export Options | Yes | Yes + More |

## Need Help?

See `FULLSTACK_README.md` for detailed documentation.
