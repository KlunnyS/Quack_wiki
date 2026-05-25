from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from forms import ArticleForm, LoginForm, RegisterForm, RoleForm
from models import Article, User, db
from seed import seed_admin

app = Flask(__name__)
app.config['SECRET_KEY'] = '#K0nMykvNSC3OyQcA'
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


def role_required(role_names: list):
    def decorator(func):
        @wraps(func)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in role_names:
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
            msg = 'An account with this email already exists.'
            form.email.errors.append(msg)
            flash(msg, 'danger')
        else:
            new_user = User(username=form.username.data, email=form.email.data)
            new_user.set_password(form.password.data)
            db.session.add(new_user)
            db.session.commit()
            flash(f'User {form.username.data} registered successfully.', 'success')
            return redirect(url_for('login'))

    return render_template('auth/register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    error = None

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if not user:
            error = 'No account exists for this email.'
            flash(error, 'danger')
        elif not check_password_hash(user.password_hash, form.password.data):
            error = 'Incorrect password.'
            flash(error, 'danger')
        else:
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))

    return render_template('auth/login.html', form=form, error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/articles/new', methods=['GET', 'POST'])
@login_required
def create_article():
    form = ArticleForm()

    if form.validate_on_submit():
        normalized_title = form.title.data.strip()
        existing = Article.query.filter_by(title=normalized_title).first()
        if existing:
            flash('Article with this title already exists.', 'danger')
            return render_template('create_article.html', form=form)

        parsed_tags = []
        if form.tags.data:
            parsed_tags = [t.strip() for t in form.tags.data.split(',') if t.strip()]

        image_url = (form.image_url.data or '').strip() or 'default.png'

        article_obj = Article(
            title=normalized_title,
            author=current_user.username,
            summary=(form.summary.data or '').strip(),
            content=form.content.data.strip(),
            image_url=image_url,
            tags=parsed_tags,
            status='pending',
            approved_by=None,
            approved_at=None,
            is_archived=False,
            archived_at=None,
        )

        try:
            db.session.add(article_obj)
            db.session.commit()
            flash('Article created successfully.', 'success')
            return redirect(url_for('article', article_title=article_obj.title))
        except SQLAlchemyError:
            db.session.rollback()
            flash('Could not create article. Check title uniqueness and field lengths.', 'danger')

    return render_template('create_article.html', form=form)


@app.route('/dashboard')
@role_required(['admin'])
def dashboard():
    return redirect(url_for('dashboard_users'))


@app.route('/dashboard/users')
@role_required(['admin'])
def dashboard_users():
    search = (request.args.get('q') or '').strip()
    role_filter = (request.args.get('role') or 'all').strip().lower()
    show_archived = request.args.get('show_archived') == '1'
    sort = (request.args.get('sort') or 'newest').strip().lower()

    query = User.query
    if not show_archived:
        query = query.filter(User.is_archived.is_(False))
    if search:
        like = f'%{search}%'
        query = query.filter((User.username.ilike(like)) | (User.email.ilike(like)))
    if role_filter in {'user', 'writer', 'admin'}:
        query = query.filter(User.role == role_filter)

    sort_map = {
        'newest': User.created_at.desc(),
        'oldest': User.created_at.asc(),
        'username_az': User.username.asc(),
        'username_za': User.username.desc(),
        'role_az': User.role.asc(),
        'role_za': User.role.desc(),
    }
    users = query.order_by(sort_map.get(sort, User.created_at.desc())).all()
    role_form = RoleForm()

    return render_template(
        'dashboard_users.html',
        users=users,
        role_form=role_form,
        search=search,
        role_filter=role_filter,
        show_archived=show_archived,
        sort=sort,
    )


@app.route('/dashboard/articles')
@role_required(['admin', 'writer'])
def dashboard_articles():
    search = (request.args.get('q') or '').strip()
    status_filter = (request.args.get('status') or 'all').strip().lower()
    show_archived = request.args.get('show_archived') == '1'
    sort = (request.args.get('sort') or 'newest').strip().lower()

    query = Article.query
    if not show_archived:
        query = query.filter(Article.is_archived.is_(False))
    if search:
        like = f'%{search}%'
        query = query.filter((Article.title.ilike(like)) | (Article.author.ilike(like)))
    if status_filter in {'pending', 'approved', 'declined'}:
        query = query.filter(Article.status == status_filter)

    sort_map = {
        'newest': Article.created_at.desc(),
        'oldest': Article.created_at.asc(),
        'title_az': Article.title.asc(),
        'title_za': Article.title.desc(),
        'status_az': Article.status.asc(),
        'status_za': Article.status.desc(),
    }
    articles = query.order_by(sort_map.get(sort, Article.created_at.desc())).all()

    return render_template(
        'dashboard_articles.html',
        articles=articles,
        search=search,
        status_filter=status_filter,
        show_archived=show_archived,
        sort=sort,
    )


@app.route('/set-role/<int:user_id>', methods=['POST'])
@role_required(['admin'])
def set_role(user_id):
    form = RoleForm()

    if form.validate_on_submit():
        user = User.query.get_or_404(user_id)
        if user.username == 'MainAdmin':
            flash('Cannot change MainAdmin role.', 'danger')
            return redirect(url_for('dashboard_users'))
        if user.is_archived:
            flash('Cannot change role for archived user.', 'danger')
            return redirect(url_for('dashboard_users'))
        if user.id == current_user.id:
            flash('You cannot change your own role.', 'danger')
            return redirect(url_for('dashboard_users'))
        if user.role == 'admin' and current_user.username != 'MainAdmin':
            flash('Only MainAdmin can change another admin role.', 'danger')
            return redirect(url_for('dashboard_users'))

        user.role = form.role.data
        db.session.commit()
        flash(f'Role updated for {user.username}.', 'success')

    return redirect(url_for('dashboard_users'))


@app.route('/users/<int:user_id>/toggle-archive', methods=['POST'])
@role_required(['admin'])
def toggle_archive_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username == 'MainAdmin':
        flash('Cannot archive MainAdmin.', 'danger')
        return redirect(url_for('dashboard_users'))
    if user.id == current_user.id:
        flash('You cannot archive your own account.', 'danger')
        return redirect(url_for('dashboard_users'))
    if user.role == 'admin' and current_user.username != 'MainAdmin':
        flash('Only MainAdmin can archive another admin.', 'danger')
        return redirect(url_for('dashboard_users'))

    user.is_archived = not user.is_archived
    user.archived_at = datetime.utcnow() if user.is_archived else None
    db.session.commit()
    flash(f"User {'deactivated' if user.is_archived else 'reactivated'}: {user.username}", 'info')
    return redirect(url_for('dashboard_users'))


@app.route('/approve/<int:article_id>', methods=['POST'])
@role_required(['admin'])
def approve(article_id):
    article_obj = Article.query.get_or_404(article_id)
    if article_obj.is_archived:
        flash('Cannot approve archived article.', 'danger')
        return redirect(url_for('dashboard_articles'))

    article_obj.status = 'approved'
    article_obj.approved_by = current_user.username
    article_obj.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f'Approved article: {article_obj.title}', 'success')
    return redirect(url_for('dashboard_articles'))


@app.route('/decline/<int:article_id>', methods=['POST'])
@role_required(['admin'])
def decline(article_id):
    article_obj = Article.query.get_or_404(article_id)
    if article_obj.is_archived:
        flash('Cannot decline archived article.', 'danger')
        return redirect(url_for('dashboard_articles'))

    article_obj.status = 'declined'
    article_obj.approved_by = current_user.username
    article_obj.approved_at = datetime.utcnow()
    db.session.commit()
    flash('Article declined.', 'warning')
    return redirect(url_for('dashboard_articles'))


@app.route('/articles/<int:article_id>/toggle-archive', methods=['POST'])
@role_required(['admin'])
def toggle_archive_article(article_id):
    article_obj = Article.query.get_or_404(article_id)
    article_obj.is_archived = not article_obj.is_archived
    article_obj.archived_at = datetime.utcnow() if article_obj.is_archived else None
    db.session.commit()
    flash(f"Article {'archived' if article_obj.is_archived else 'restored'}: {article_obj.title}", 'info')
    return redirect(url_for('dashboard_articles'))


@app.route('/article/<article_title>')
def article(article_title):
    article_obj = Article.query.filter_by(title=article_title, is_archived=False).first_or_404()
    return render_template('article.html', article=article_obj, random_article=None)
