from biblio.app import app
from biblio.models import db, User

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            admin_user = User(username="admin", password="admin", role="admin")
            db.session.add(admin_user)
            db.session.commit()
            print("✅ Utilisateur admin créé (login: admin / mot de passe: admin)")
        else:
            print("✅ Utilisateur admin déjà présent.")
    print("🚀 Serveur démarré sur http://localhost:5000")
    app.run(debug=True, port=5000)
