from biblio.app import app
from biblio.models import db, User

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin_user = User(username="admin", password="admin", role="admin")
        db.session.add(admin_user)
        db.session.commit()

application = app
