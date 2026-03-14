# biblio/app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from biblio.models import db, User, Livre, Historique, Reservation
from biblio.forms import LivreForm
from biblio import settings_manager as sm
from biblio import notification_manager
import pandas as pd
from io import BytesIO
from sqlalchemy import or_
import os
from flask_dance.contrib.google import make_google_blueprint, google

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'votre_cle_secrete_ici_beaucoup_plus_longue_et_complexe')

if os.environ.get('FLASK_ENV') != 'production':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- GOOGLE OAUTH ---
google_bp = make_google_blueprint(
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
    redirect_to='google_login_callback'
)
app.register_blueprint(google_bp, url_prefix='/login')

# --- DATABASE ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///biblio.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

@app.template_filter('format_datetime')
def format_datetime_filter(value, format="%d %B %Y à %Hh%M"):
    if not value:
        return "Date non disponible"
    if isinstance(value, str):
        try:
            if value.endswith('Z'):
                value = value[:-1]
            value_dt = datetime.fromisoformat(value)
        except ValueError:
            try:
                value_dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f")
            except ValueError:
                try:
                    value_dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    return value
    elif isinstance(value, datetime):
        value_dt = value
    else:
        return value
    return value_dt.strftime(format)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def inject_notifications():
    if current_user.is_authenticated:
        notifications = notification_manager.get_and_clear_notifications(current_user.id)
        for notif in notifications:
            flash(notif['message'], notif['category'])

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Accès non autorisé.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# AUTHENTIFICATION
# ==============================================================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash("Ce nom d'utilisateur existe déjà.", "danger")
        else:
            new_user = User(username=username, password=password)
            db.session.add(new_user)
            db.session.commit()
            flash("Inscription réussie !", "success")
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f"Bienvenue, {user.username} !", "success")
            return redirect(url_for('index'))
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Vous avez été déconnecté.", "success")
    return redirect(url_for('index'))

@app.route('/google/callback')
def google_login_callback():
    if not google.authorized:
        flash("Connexion Google annulée.", "danger")
        return redirect(url_for('login'))
    try:
        resp = google.get("/oauth2/v2/userinfo")
        if not resp.ok:
            flash("Impossible de récupérer les informations Google.", "danger")
            return redirect(url_for('login'))
        google_info = resp.json()
        google_email = google_info.get("email")
        if not google_email:
            flash("Email Google non disponible.", "danger")
            return redirect(url_for('login'))
        user = User.query.filter_by(username=google_email).first()
        if not user:
            new_user = User(username=google_email, password="google_oauth_no_password", role="user")
            db.session.add(new_user)
            db.session.commit()
            user = new_user
            flash("Compte créé et connecté avec Google !", "success")
        else:
            flash(f"Bienvenue, {user.username} !", "success")
        login_user(user)
        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Erreur Google : {str(e)}", "danger")
        return redirect(url_for('login'))

# ==============================================================================
# ROUTES PRINCIPALES
# ==============================================================================

@app.route('/')
def index():
    query = request.args.get('recherche', '').strip()
    sort_by = request.args.get('tri', 'note_desc')
    show_available_only = request.args.get('disponibilite', 'false') == 'true'
    selected_genres = request.args.getlist('genre_filter')

    livres_query = Livre.query
    if query:
        search_term = f"%{query.lower()}%"
        livres_query = livres_query.filter(db.or_(Livre.titre.ilike(search_term), Livre.auteur.ilike(search_term), Livre.annee.ilike(search_term)))
    if show_available_only:
        livres_query = livres_query.filter(Livre.statut_etat == 'disponible')
    if selected_genres:
        livres_query = livres_query.filter(Livre.genre.in_(selected_genres))

    if sort_by == 'titre_asc':
        livres_query = livres_query.order_by(Livre.titre.asc())
    elif sort_by == 'auteur_asc':
        livres_query = livres_query.order_by(Livre.auteur.asc())
    elif sort_by == 'annee_desc':
        livres_query = livres_query.order_by(Livre.annee.desc())
    elif sort_by == 'annee_asc':
        livres_query = livres_query.order_by(Livre.annee.asc())
    else:
        livres_query = livres_query.order_by(Livre.note.desc(), Livre.titre.asc())

    page = request.args.get('page', 1, type=int)
    per_page = 12
    pagination_obj = livres_query.paginate(page=page, per_page=per_page, error_out=False)
    tous_les_livres_pagines = pagination_obj.items

    livres_par_genre = defaultdict(list)
    if not query and not selected_genres:
        for livre in tous_les_livres_pagines:
            livres_par_genre[livre.genre if livre.genre else "Non classé"].append(livre)
    else:
        livres_par_genre["Résultats"] = tous_les_livres_pagines

    total_livres_count = Livre.query.count()
    livres_empruntes_count = Livre.query.filter(Livre.statut_etat.in_(['emprunté', 'retour_en_attente'])).count()
    all_available_genres = sorted(list(set(g[0] for g in Livre.query.with_entities(Livre.genre).distinct() if g[0])))

    if query and not tous_les_livres_pagines:
        flash(f"Aucun livre ne correspond à '{query}'.", "info")

    return render_template('index.html',
                           livres_par_genre=dict(livres_par_genre),
                           query=query,
                           livres_empruntes_count=livres_empruntes_count,
                           total_livres=total_livres_count,
                           tri=sort_by,
                           pagination=pagination_obj,
                           show_available_only=show_available_only,
                           all_available_genres=all_available_genres,
                           selected_genres=selected_genres)

@app.route('/search_realtime')
def search_realtime():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify([])
    search_term = f"%{query.lower()}%"
    livres = Livre.query.filter(db.or_(Livre.titre.ilike(search_term), Livre.auteur.ilike(search_term), Livre.annee.ilike(search_term))).limit(10).all()
    results = [{'titre': l.titre, 'auteur': l.auteur, 'note': l.note,
                'image_url': l.image_url or '',
                'details_url': url_for('details_livre', livre_id=l.id)} for l in livres]
    return jsonify(results)

@app.route('/livre/<int:livre_id>')
def details_livre(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    recommandations = Livre.query.filter(Livre.id != livre.id, or_(Livre.genre == livre.genre, Livre.auteur == livre.auteur)).order_by(db.func.random()).limit(4).all()
    return render_template('details_livre.html', livre=livre, recommandations=recommandations)

@app.route('/profil')
@login_required
def profil():
    livres_empruntes_obj = Livre.query.filter(Livre.emprunte_par_id == current_user.id, Livre.statut_etat.in_(['emprunté', 'retour_en_attente'])).all()
    livres_empruntes_actuellement_details = []
    for livre_emprunte in livres_empruntes_obj:
        historique_actif = Historique.query.filter_by(media_id=livre_emprunte.id, user_id=current_user.id, date_retour=None).order_by(Historique.date_emprunt.desc()).first()
        date_emprunt = historique_actif.date_emprunt if historique_actif else None
        date_retour_prevue = historique_actif.date_retour_prevue if historique_actif else None
        est_en_retard = date_retour_prevue and date_retour_prevue < datetime.utcnow() if date_retour_prevue else False
        livres_empruntes_actuellement_details.append({'livre': livre_emprunte, 'date_emprunt': date_emprunt, 'date_retour_prevue': date_retour_prevue, 'est_en_retard': est_en_retard, 'image_url': livre_emprunte.image_url})
    historique_emprunts_complet = Historique.query.filter_by(user_id=current_user.id).order_by(Historique.date_emprunt.desc()).all()
    reservations_utilisateur = Reservation.query.filter_by(user_id=current_user.id).order_by(Reservation.date_reservation.asc()).all()
    return render_template('profil.html', livres_empruntes_details=livres_empruntes_actuellement_details, historique_emprunts=historique_emprunts_complet, reservations_utilisateur=reservations_utilisateur, now=datetime.utcnow())

@app.route('/annuler-reservation/<int:reservation_id>', methods=['POST'])
@login_required
def annuler_reservation(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != current_user.id:
        flash("Non autorisé.", "danger")
        return redirect(url_for('profil'))
    livre_titre = reservation.livre.titre if reservation.livre else "Titre inconnu"
    db.session.delete(reservation)
    db.session.commit()
    flash(f"Réservation pour '{livre_titre}' annulée.", "success")
    return redirect(url_for('profil'))

# ==============================================================================
# GESTION DES LIVRES
# ==============================================================================

@app.route('/ajouter', methods=['GET', 'POST'])
@admin_required
def ajouter():
    form = LivreForm()
    form.genre.choices = [(cat, cat) for cat in sm.get_categories()]
    if form.validate_on_submit():
        if Livre.query.filter(db.func.lower(Livre.titre) == db.func.lower(form.titre.data)).first():
            form.titre.errors.append(f"Le livre '{form.titre.data}' existe déjà.")
        else:
            new_livre = Livre(titre=form.titre.data.strip(), auteur=form.auteur.data.strip(), annee=str(form.annee.data), genre=form.genre.data, note=form.note.data, description=form.description.data, image_url=form.image_url.data if form.image_url.data else None)
            db.session.add(new_livre)
            db.session.commit()
            flash(f"Le livre '{new_livre.titre}' a été ajouté.", "success")
            return redirect(url_for('index'))
    elif request.method == 'POST':
        flash("Erreur dans le formulaire.", "danger")
    return render_template('ajouter.html', form=form)

@app.route('/modifier/<int:livre_id>', methods=['GET', 'POST'])
@admin_required
def modifier(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    form = LivreForm(obj=livre)
    form.genre.choices = [(cat, cat) for cat in sm.get_categories()]
    if form.validate_on_submit():
        nouveau_titre = form.titre.data.strip()
        existing = Livre.query.filter(db.func.lower(Livre.titre) == db.func.lower(nouveau_titre)).first()
        if nouveau_titre.lower() != livre.titre.lower() and existing:
            flash("Ce titre est déjà utilisé.", "danger")
        else:
            livre.titre = nouveau_titre
            livre.auteur = form.auteur.data.strip()
            livre.annee = str(form.annee.data)
            livre.genre = form.genre.data
            livre.note = form.note.data
            livre.description = form.description.data
            livre.image_url = form.image_url.data if form.image_url.data else None
            db.session.commit()
            flash(f"Livre '{livre.titre}' mis à jour.", "success")
            return redirect(url_for('details_livre', livre_id=livre.id))
    elif request.method == 'POST':
        flash("Erreur dans le formulaire.", "danger")
    return render_template('modifier.html', form=form, livre=livre)

@app.route('/supprimer/<int:livre_id>')
@admin_required
def supprimer(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    if livre.statut_etat != 'disponible' or Reservation.query.filter_by(media_id=livre.id).first():
        flash("Impossible de supprimer un livre emprunté ou avec réservations.", "danger")
    else:
        Historique.query.filter_by(media_id=livre.id).delete()
        db.session.delete(livre)
        db.session.commit()
        flash(f"Le livre '{livre.titre}' a été supprimé.", "success")
    return redirect(url_for('index'))

# ==============================================================================
# EMPRUNTS / RETOURS
# ==============================================================================

@app.route('/demander-emprunt/<int:livre_id>')
@login_required
def demander_emprunt(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    try:
        livre.demander_emprunt(current_user)
        db.session.commit()
        flash(f"Demande d'emprunt pour '{livre.titre}' enregistrée.", "success")
    except ValueError as e:
        flash(str(e), "warning")
    return redirect(request.referrer or url_for('index'))

@app.route('/approuver-emprunt/<int:livre_id>')
@admin_required
def approuver_emprunt_route(livre_id):
    livre = Livre.query.filter(Livre.id == livre_id, Livre.statut_etat == 'demande_emprunt_en_attente').first_or_404()
    demandeur_id = livre.emprunte_par_id
    demandeur = User.query.get(demandeur_id)
    if not demandeur:
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for('admin_dashboard'))
    try:
        livre.approuver_emprunt()
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for('admin_dashboard'))
    loan_duration_days = sm.get_setting('loan_duration_days', 14)
    date_retour_prevue = datetime.utcnow() + timedelta(days=loan_duration_days)
    nouvel_historique = Historique(user_id=demandeur_id, media_id=livre.id, date_emprunt=datetime.utcnow(), date_retour_prevue=date_retour_prevue)
    db.session.add(nouvel_historique)
    db.session.commit()
    flash(f"Emprunt de '{livre.titre}' approuvé.", "success")
    template = sm.get_notification_template('loan_approved')
    notification_manager.add_notification(demandeur_id, template.format(livre_titre=livre.titre), 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/refuser-emprunt/<int:livre_id>')
@admin_required
def refuser_emprunt_route(livre_id):
    livre = Livre.query.filter(Livre.id == livre_id, Livre.statut_etat == 'demande_emprunt_en_attente').first_or_404()
    demandeur_id = livre.emprunte_par_id
    try:
        livre.refuser_emprunt()
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for('admin_dashboard'))
    db.session.commit()
    flash(f"Demande refusée pour '{livre.titre}'.", "info")
    if demandeur_id:
        template = sm.get_notification_template('loan_refused')
        notification_manager.add_notification(demandeur_id, template.format(livre_titre=livre.titre), 'warning')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/demander-retour/<int:livre_id>')
@login_required
def demander_retour(livre_id):
    livre = Livre.query.filter(Livre.id == livre_id, Livre.emprunte_par_id == current_user.id, Livre.statut_etat == 'emprunté').first_or_404()
    livre.statut_etat = 'retour_en_attente'
    db.session.commit()
    flash(f"Demande de retour pour '{livre.titre}' envoyée.", "success")
    return redirect(request.referrer or url_for('profil'))

@app.route('/approuver-retour/<int:livre_id>')
@admin_required
def approuver_retour(livre_id):
    livre = Livre.query.filter(Livre.id == livre_id, Livre.statut_etat == 'retour_en_attente').first_or_404()
    historique_entry = Historique.query.filter_by(media_id=livre.id, user_id=livre.emprunte_par_id, date_retour=None).order_by(Historique.date_emprunt.desc()).first()
    if historique_entry:
        historique_entry.date_retour = datetime.utcnow()
    prochaine_reservation = Reservation.query.filter_by(media_id=livre.id).order_by(Reservation.date_reservation.asc()).first()
    if prochaine_reservation:
        next_user = User.query.get(prochaine_reservation.user_id)
        if next_user:
            livre.statut_etat = 'demande_emprunt_en_attente'
            livre.emprunte_par_id = prochaine_reservation.user_id
            db.session.delete(prochaine_reservation)
            flash(f"'{livre.titre}' retourné et mis en attente pour {next_user.username}.", "success")
        else:
            livre.statut_etat = 'disponible'
            livre.emprunte_par_id = None
            db.session.delete(prochaine_reservation)
    else:
        livre.statut_etat = 'disponible'
        livre.emprunte_par_id = None
        flash(f"Retour de '{livre.titre}' approuvé.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/reserver/<int:livre_id>')
@login_required
def reserver(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    if livre.statut_etat not in ['emprunté', 'retour_en_attente']:
        flash("Vous ne pouvez réserver qu'un livre déjà emprunté.", "warning")
        return redirect(request.referrer or url_for('details_livre', livre_id=livre_id))
    if livre.emprunte_par_id == current_user.id:
        flash("Vous ne pouvez pas réserver un livre que vous avez emprunté.", "warning")
        return redirect(request.referrer or url_for('details_livre', livre_id=livre_id))
    if Reservation.query.filter_by(media_id=livre.id, user_id=current_user.id).first():
        flash("Vous avez déjà réservé ce livre.", "info")
        return redirect(request.referrer or url_for('details_livre', livre_id=livre_id))
    new_reservation = Reservation(user_id=current_user.id, media_id=livre.id)
    db.session.add(new_reservation)
    db.session.commit()
    flash(f"Réservation pour '{livre.titre}' enregistrée.", "success")
    return redirect(request.referrer or url_for('details_livre', livre_id=livre_id))

# ==============================================================================
# ADMIN
# ==============================================================================

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    demandes_emprunt = Livre.query.filter_by(statut_etat='demande_emprunt_en_attente').all()
    demandes_retour = Livre.query.filter_by(statut_etat='retour_en_attente').all()
    livres_actuellement_empruntes = Historique.query.join(Livre, Livre.id == Historique.media_id).filter(Livre.statut_etat == 'emprunté', Historique.date_retour == None).order_by(Historique.date_emprunt.asc()).all()
    livres_en_retard = Historique.query.filter(Historique.date_retour == None, Historique.date_retour_prevue < datetime.utcnow()).order_by(Historique.date_retour_prevue.asc()).all()
    return render_template('admin_dashboard.html', livres_en_demande_emprunt=demandes_emprunt, livres_en_attente_retour=demandes_retour, livres_actuellement_empruntes=livres_actuellement_empruntes, livres_en_retard=livres_en_retard, now=datetime.utcnow())

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save_main_settings':
            try:
                sm.update_setting('max_loans_per_user', int(request.form.get('max_loans_per_user', 5)))
                sm.update_setting('loan_duration_days', int(request.form.get('loan_duration_days', 14)))
                templates = sm.get_setting('notification_templates', {})
                templates['loan_approved'] = request.form.get('loan_approved', templates.get('loan_approved', ''))
                templates['loan_refused'] = request.form.get('loan_refused', templates.get('loan_refused', ''))
                sm.update_setting('notification_templates', templates)
                flash("Paramètres enregistrés.", "success")
            except ValueError:
                flash("Valeurs invalides.", "danger")
    return render_template('settings.html', settings=sm.load_settings())

@app.route('/admin/category/add', methods=['POST'])
@admin_required
def add_category():
    category_name = request.form.get('category_name', '').strip()
    if category_name:
        categories = sm.get_categories()
        if category_name not in categories:
            categories.append(category_name)
            sm.update_setting('categories', sorted(list(set(categories))))
            flash(f"Catégorie '{category_name}' ajoutée.", "success")
        else:
            flash(f"Catégorie '{category_name}' existe déjà.", "info")
    else:
        flash("Nom vide.", "warning")
    return redirect(url_for('settings'))

@app.route('/admin/category/delete/<category_name>')
@admin_required
def delete_category(category_name):
    categories = sm.get_categories()
    if category_name in categories:
        if Livre.query.filter_by(genre=category_name).first():
            flash(f"Catégorie '{category_name}' utilisée par des livres.", "danger")
        else:
            categories.remove(category_name)
            sm.update_setting('categories', categories)
            flash(f"Catégorie '{category_name}' supprimée.", "success")
    return redirect(url_for('settings'))

@app.route('/admin/statistics')
@admin_required
def statistics():
    stats_data = {
        'total_books': Livre.query.count(),
        'total_users': User.query.count(),
        'total_loans': Historique.query.count(),
        'current_loans': Livre.query.filter(Livre.statut_etat.in_(['emprunté', 'retour_en_attente'])).count(),
        'overdue_books': Historique.query.filter(Historique.date_retour == None, Historique.date_retour_prevue < datetime.utcnow()).count()
    }
    popular_books_query = db.session.query(Livre.titre, db.func.count(Historique.id).label('loan_count')).join(Historique, Livre.id == Historique.media_id).group_by(Livre.titre).order_by(db.desc('loan_count')).limit(7).all()
    active_readers_query = db.session.query(User.username, db.func.count(Historique.id).label('loan_count')).join(Historique, User.id == Historique.user_id).group_by(User.username).order_by(db.desc('loan_count')).limit(7).all()
    return render_template('statistics.html', stats=stats_data,
                           popular_books_chart_labels=[i[0] for i in popular_books_query],
                           popular_books_chart_data=[i[1] for i in popular_books_query],
                           active_readers_chart_labels=[i[0] for i in active_readers_query],
                           active_readers_chart_data=[i[1] for i in active_readers_query],
                           top_5_popular_books=popular_books_query[:5],
                           top_5_active_readers=active_readers_query[:5])

@app.route('/admin/export/<report_type>')
@admin_required
def export_report(report_type):
    df = None
    if report_type == 'popular_books':
        data_query = db.session.query(Livre.titre, Livre.auteur, db.func.count(Historique.id).label('nombre_emprunts')).outerjoin(Historique, Livre.id == Historique.media_id).group_by(Livre.id, Livre.titre, Livre.auteur).order_by(db.desc('nombre_emprunts')).all()
        df = pd.DataFrame(data_query, columns=['Livre', 'Auteur', "Nombre d'emprunts"])
    elif report_type == 'active_readers':
        data_query = db.session.query(User.username, db.func.count(Historique.id).label('nombre_emprunts')).outerjoin(Historique, User.id == Historique.user_id).group_by(User.id, User.username).order_by(db.desc('nombre_emprunts')).all()
        df = pd.DataFrame(data_query, columns=['Lecteur', "Nombre d'emprunts"])
    else:
        flash("Type de rapport invalide.", "danger")
        return redirect(url_for('statistics'))
    if df is None or df.empty:
        flash("Aucune donnée à exporter.", "info")
        return redirect(url_for('statistics'))
    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Rapport')
        output.seek(0)
        return send_file(output, download_name=f'rapport_{report_type}_{datetime.now().strftime("%Y%m%d")}.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash("Erreur lors de la génération du rapport.", "danger")
        return redirect(url_for('statistics'))

@app.cli.command("init-db")
def init_db_command():
    db.create_all()
    print("Base de données initialisée.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            admin_user = User(username="admin", password="admin", role="admin")
            db.session.add(admin_user)
            db.session.commit()
    app.run(debug=True, port=5000)
