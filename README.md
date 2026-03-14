# 📚 BiblioFlask

Application web de gestion de bibliothèque construite avec Flask, SQLAlchemy et PostgreSQL.

## 🌐 Site en ligne
**https://biblioflask.vercel.app/**

## 🖥️ Lancer en local

```bash
python -m venv venv
source venv/bin/activate  # Mac/Linux
venv\Scripts\activate     # Windows
pip install -r requirements.txt
python run.py
```

Ouvre **http://localhost:5000** — Login : `admin` / `admin`

## 🚀 Variables d'environnement (Vercel)

| Variable | Description |
|---|---|
| `SECRET_KEY` | Clé secrète Flask |
| `DATABASE_URL` | URL PostgreSQL (Neon) |
| `GOOGLE_CLIENT_ID` | Client ID Google OAuth |
| `GOOGLE_CLIENT_SECRET` | Client Secret Google OAuth |

## 📁 Stack technique
- **Backend** : Flask, Flask-SQLAlchemy, Flask-Login, Flask-Dance
- **Base de données** : PostgreSQL (Neon) en production, SQLite en local
- **Hébergement** : Vercel
- **Auth** : Login classique + Google OAuth
