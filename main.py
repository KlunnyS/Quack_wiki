from flask import Flask, render_template, redirect, url_for, flash, request, session,abort
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from uuid import uuid4
import os
import random
from functools import wraps


from flask_login import LoginManager, login_user, logout_user, current_user, login_required

from forms import LoginForm, RegisterForm, RoleForm, ArticleForm
from models import db, User, Article
from seed import seed_admin

app = Flask(__name__)
app.config['SECRET_KEY'] = '#K0nMykvNSC3OyQcA'  # zmeň na vlastné
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pages.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/img/upload'

db.init_app(app)

with app.app_context():
    db.create_all()
    seed_admin()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def role_required(role_name:list):
    def decorator(func):
        @wraps(func)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in role_name:
                abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data).first()

        if existing_user:
            form.email.errors.append("Už existuje účet s týmto emailom.")
            flash("Už existuje účet s týmto emailom.","danger")
        else:
            new_user = User( username=form.username.data, email=form.email.data)
            new_user.set_password(form.password.data)

            db.session.add(new_user)
            db.session.commit()

            flash(f"Používateľ {form.username.data} úspešne zaregistrovaný","success")
            return redirect(url_for('login'))

    return render_template('auth/register.html', form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    error = None

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if not user:
            error = "Používateľ s týmto emailom neexistuje."
            flash(error,"danger")

        elif not check_password_hash(user.password_hash, form.password.data):
            error = "Nesprávne heslo."
            flash(error,"danger")

        else:
            login_user(user)
            flash("Používateľ úspešne prihlásený","success")
            return redirect(url_for("index"))

    return render_template("auth/login.html", form=form, error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Používateľ úspešne odhlásený","success")
    return redirect(url_for('index'))

@app.route('/')
def index():
    return render_template('index.html')


# ===============================
# ========== Dashboard ==========
# ===============================

@app.route('/dashboard')    
@role_required(["admin"])
def dashboard():
    users = User.query.all()
    articles = Article.query.all() 
    role_form = RoleForm()
    return render_template("dashboard.html",users=users,role_form=role_form,articles=articles)

@app.route("/set-role/<int:user_id>", methods=["POST"])
@role_required(["admin"])
def set_role(user_id):
    form = RoleForm()

    if form.validate_on_submit():
        user = User.query.get_or_404(user_id)
        if user.username != "MainAdmin":
            user.role = form.role.data
            db.session.commit()
        else: flash("Cannot change main admin's role!!!","danger")

    return redirect(url_for("dashboard"))

@app.route("/approve/<int:article_id>", methods=["POST"])
@role_required(["admin"])
def approve(article_id):
    return redirect(url_for("dashboard"))

@app.route("/decline/<int:article_id>", methods=["POST"])
@role_required(["admin"])
def decline(article_id):
    return redirect(url_for("dashboard"))

# ===============================
# =========== Article ===========
# ===============================

@app.route("/article/<article_title>")
def article(article_title):
    id = Article.query.filter_by(title=article_title)
    article = Article.query.get_or_404(id)

    # all_articles = Article.query.filter(Article.id != article_id).all() 
    # random_article = random.choice(all_articles) if all_articles else None
    return render_template("aticle.html",article=article)
                                        #,article=article,random_article=random_article