# ChronoBirth

App PWA profilo astrologico.

## Locale (Windows)
Doppio click su `avvia.bat` → http://127.0.0.1:8080/index.html

## Locale (terminale)
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

## GitHub Pages
Carica questa cartella sul repo e attiva Pages (branch `main`, folder `/root`).

## Render (API opzionale)
- Root Directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
