"""
Script d'import des livres depuis SQLite vers PostgreSQL (Neon).
Usage : python import_to_neon.py
"""
import sqlite3
import psycopg2
import sys

DATABASE_URL = "postgresql://neondb_owner:npg_3eTjYG0PmUQk@ep-winter-breeze-ad3dr262-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
SQLITE_PATH = "instance/biblio.db"

def import_data():
    print("📖 Lecture de la base SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute("""
        SELECT m.titre, m.annee, m.description, m.statut_etat,
               l.auteur, l.genre, l.note, l.image_url
        FROM media m JOIN livre l ON m.id = l.id
    """)
    livres = sqlite_cursor.fetchall()
    print(f"  ✅ {len(livres)} livres trouvés")
    sqlite_cursor.execute("SELECT username, password, role FROM user WHERE role='admin'")
    admins = sqlite_cursor.fetchall()
    sqlite_conn.close()

    print("\n🔌 Connexion à PostgreSQL (Neon)...")
    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_cursor = pg_conn.cursor()
    print("  ✅ Connecté !")

    pg_cursor.execute("""CREATE TABLE IF NOT EXISTS "user" (id SERIAL PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, password VARCHAR(120) NOT NULL, role VARCHAR(20) NOT NULL DEFAULT 'user')""")
    pg_cursor.execute("""CREATE TABLE IF NOT EXISTS media (id SERIAL PRIMARY KEY, titre VARCHAR(150) UNIQUE NOT NULL, annee VARCHAR(4), description TEXT, statut_etat VARCHAR(50) NOT NULL DEFAULT 'disponible', emprunte_par_id INTEGER REFERENCES "user"(id), type VARCHAR(50))""")
    pg_cursor.execute("""CREATE TABLE IF NOT EXISTS livre (id INTEGER PRIMARY KEY REFERENCES media(id), auteur VARCHAR(100) NOT NULL, genre VARCHAR(50), note INTEGER, image_url VARCHAR(255))""")
    pg_cursor.execute("""CREATE TABLE IF NOT EXISTS historique (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id), media_id INTEGER REFERENCES media(id), date_emprunt TIMESTAMP NOT NULL DEFAULT NOW(), date_retour TIMESTAMP, date_retour_prevue TIMESTAMP)""")
    pg_cursor.execute("""CREATE TABLE IF NOT EXISTS reservation (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id), media_id INTEGER NOT NULL REFERENCES media(id), date_reservation TIMESTAMP NOT NULL DEFAULT NOW())""")
    pg_conn.commit()

    for admin in admins:
        pg_cursor.execute('INSERT INTO "user" (username, password, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING', admin)
    pg_conn.commit()
    print("  ✅ Admin importé !")

    imported = 0
    for livre in livres:
        titre, annee, description, statut_etat, auteur, genre, note, image_url = livre
        try:
            img = image_url[:255] if image_url else None
            pg_cursor.execute("INSERT INTO media (titre, annee, description, statut_etat, type) VALUES (%s, %s, %s, 'disponible', 'livre') ON CONFLICT (titre) DO NOTHING RETURNING id", (titre, annee, description))
            result = pg_cursor.fetchone()
            if result:
                pg_cursor.execute("INSERT INTO livre (id, auteur, genre, note, image_url) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING", (result[0], auteur, genre, note, img))
                imported += 1
                print(f"  ✅ '{titre}' importé")
        except Exception as e:
            print(f"  ❌ '{titre}': {e}")
            pg_conn.rollback()
    pg_conn.commit()
    pg_conn.close()
    print(f"\n🎉 {imported} livres importés ! Vérifie : https://biblioflask.vercel.app/")

if __name__ == '__main__':
    import_data()
