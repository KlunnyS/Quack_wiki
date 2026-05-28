from datetime import datetime
import html
import os
import re
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from uuid import uuid4

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
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
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
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


def _inline_markdown(text: str) -> str:
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', text)
    return text


def render_simple_markdown(raw_text: str) -> str:
    if not raw_text:
        return '<p>No content yet.</p>'

    text = html.escape(raw_text.strip())
    lines = text.splitlines()
    blocks = []
    in_ul = False
    in_ol = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            blocks.append('</ul>')
            in_ul = False
        if in_ol:
            blocks.append('</ol>')
            in_ol = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_lists()
            continue

        if stripped.startswith('### '):
            close_lists()
            blocks.append(f"<h3>{_inline_markdown(stripped[4:])}</h3>")
            continue
        if stripped.startswith('## '):
            close_lists()
            blocks.append(f"<h2>{_inline_markdown(stripped[3:])}</h2>")
            continue
        if stripped.startswith('# '):
            close_lists()
            blocks.append(f"<h1>{_inline_markdown(stripped[2:])}</h1>")
            continue
        if stripped.startswith('> '):
            close_lists()
            blocks.append(f"<blockquote>{_inline_markdown(stripped[2:])}</blockquote>")
            continue
        if re.match(r'^\d+\.\s+', stripped):
            if in_ul:
                blocks.append('</ul>')
                in_ul = False
            if not in_ol:
                blocks.append('<ol>')
                in_ol = True
            item = re.sub(r'^\d+\.\s+', '', stripped)
            blocks.append(f"<li>{_inline_markdown(item)}</li>")
            continue
        if stripped.startswith('- '):
            if in_ol:
                blocks.append('</ol>')
                in_ol = False
            if not in_ul:
                blocks.append('<ul>')
                in_ul = True
            blocks.append(f"<li>{_inline_markdown(stripped[2:])}</li>")
            continue

        close_lists()
        blocks.append(f"<p>{_inline_markdown(stripped)}</p>")

    close_lists()
    return '\n'.join(blocks)


def article_public_url(article_obj: Article) -> str:
    if article_has_tag(article_obj, static_page_tag('about-us')):
        return url_for('about')
    return url_for('article', article_title=article_obj.title)


def static_page_tag(page_key: str) -> str:
    return f"page:{page_key.strip().lower()}"


def article_has_tag(article_obj: Article, tag_name: str) -> bool:
    wanted = tag_name.strip().lower()
    return any(str(tag).strip().lower() == wanted for tag in (article_obj.tags or []))


def article_matches_search(article_obj: Article, search: str) -> bool:
    needle = search.strip().lower()
    if not needle:
        return True

    fields = [
        article_obj.title or '',
        article_obj.summary or '',
        article_obj.author or '',
    ]
    tags = [str(tag) for tag in (article_obj.tags or [])]
    return any(needle in value.lower() for value in fields + tags)


def find_published_article_by_tag(tag_name: str):
    page_tag = static_page_tag(tag_name)
    candidates = Article.query.filter(
        Article.is_archived.is_(False),
        func.lower(func.trim(Article.status)) == 'approved',
    ).order_by(Article.created_at.desc()).all()
    return next(
        (article_obj for article_obj in candidates if article_has_tag(article_obj, page_tag)),
        None,
    )


def normalize_article_tags(raw_tags: str):
    tags = []
    removed_reserved = False
    can_use_reserved = current_user.is_authenticated and current_user.role in ['admin', 'writer']

    for raw_tag in (raw_tags or '').split(','):
        tag = raw_tag.strip().lower()
        if not tag:
            continue
        if tag.startswith('page:') and not can_use_reserved:
            removed_reserved = True
            continue
        if tag not in tags:
            tags.append(tag)

    return tags, removed_reserved


def can_edit_article(article_obj: Article) -> bool:
    if not current_user.is_authenticated:
        return False
    if current_user.role in ['admin', 'writer']:
        return True
    return False


def parse_infobox_data(raw_data: str):
    rows = []
    for raw_line in (raw_data or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ':' in line:
            label, value = line.split(':', 1)
            rows.append((label.strip(), value.strip()))
        else:
            rows.append((line, ''))
    return rows


def save_article_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None

    safe_name = secure_filename(file_storage.filename)
    if not safe_name:
        return None

    _, ext = os.path.splitext(safe_name)
    filename = f"{uuid4().hex}{ext.lower()}"
    upload_dir = app.config['UPLOAD_FOLDER']
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return f"upload/{filename}"


def render_article_page(article_obj: Article):
    rendered_content = render_simple_markdown(article_obj.content)
    infobox_rows = parse_infobox_data(article_obj.infobox_data)
    if not infobox_rows:
        infobox_rows = [
            ('Author', article_obj.author or 'Unknown'),
            ('Created', article_obj.created_at.strftime('%Y-%m-%d') if article_obj.created_at else 'Unknown'),
            ('Status', article_obj.status),
        ]
    return render_template(
        'article.html',
        article=article_obj,
        random_article=None,
        rendered_content=rendered_content,
        infobox_rows=infobox_rows,
        article_link=article_public_url(article_obj),
        can_edit=can_edit_article(article_obj),
    )


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


@app.route('/about')
def about():
    about_article = find_published_article_by_tag('about-us')
    if about_article:
        return render_article_page(about_article)
    flash('About article is not published yet.', 'info')
    return redirect(url_for('index'))


@app.route('/wiki/<tag>')
def tagged_article(tag):
    article_obj = find_published_article_by_tag(tag)
    if article_obj:
        return render_article_page(article_obj)
    flash(f'No published article found for tag: {tag}', 'info')
    return redirect(url_for('articles'))


@app.route('/articles')
def articles():
    search = (request.args.get('q') or '').strip()
    query = Article.query.filter(
        Article.is_archived.is_(False),
        func.lower(func.trim(Article.status)) == 'approved',
    )
    article_list = query.order_by(Article.created_at.desc()).all()
    if search:
        article_list = [article_obj for article_obj in article_list if article_matches_search(article_obj, search)]
    article_links = {article.id: article_public_url(article) for article in article_list}
    return render_template('articles.html', articles=article_list, search=search, article_links=article_links)


@app.route('/articles/new', methods=['GET', 'POST'])
@login_required
def create_article():
    form = ArticleForm()

    if form.validate_on_submit():
        normalized_title = form.title.data.strip()
        existing = Article.query.filter_by(title=normalized_title).first()
        if existing:
            flash('Article with this title already exists.', 'danger')
            return render_template('create_article.html', form=form, is_edit=False, article=None)

        parsed_tags, removed_reserved = normalize_article_tags(form.tags.data)
        if removed_reserved:
            flash('Reserved page tags can only be used by writers and admins.', 'warning')

        image_path = save_article_image(form.image_file.data) or 'default.png'

        article_obj = Article(
            title=normalized_title,
            author=current_user.username,
            summary=(form.summary.data or '').strip(),
            content=form.content.data.strip(),
            infobox_data=(form.infobox_data.data or '').strip(),
            image_url=image_path,
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

    return render_template('create_article.html', form=form, is_edit=False, article=None)


@app.route('/articles/<int:article_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_article(article_id):
    article_obj = Article.query.get_or_404(article_id)
    if not can_edit_article(article_obj):
        abort(403)

    form = ArticleForm(obj=article_obj)
    if request.method == 'GET':
        form.tags.data = ', '.join(article_obj.tags or [])
        form.infobox_data.data = article_obj.infobox_data or ''

    if form.validate_on_submit():
        normalized_title = form.title.data.strip()
        duplicate = Article.query.filter(
            Article.title == normalized_title,
            Article.id != article_obj.id,
        ).first()
        if duplicate:
            flash('Article with this title already exists.', 'danger')
            return render_template('create_article.html', form=form, is_edit=True, article=article_obj)

        article_obj.title = normalized_title
        article_obj.summary = (form.summary.data or '').strip()
        article_obj.content = form.content.data.strip()
        article_obj.infobox_data = (form.infobox_data.data or '').strip()
        uploaded_image = save_article_image(form.image_file.data)
        if uploaded_image:
            article_obj.image_url = uploaded_image
        parsed_tags, removed_reserved = normalize_article_tags(form.tags.data)
        if removed_reserved:
            flash('Reserved page tags can only be used by writers and admins.', 'warning')
        article_obj.tags = parsed_tags

        if current_user.role != 'admin':
            article_obj.status = 'pending'
            article_obj.approved_by = None
            article_obj.approved_at = None

        db.session.commit()
        flash('Article updated successfully.', 'success')
        return redirect(article_public_url(article_obj))

    return render_template('create_article.html', form=form, is_edit=True, article=article_obj)


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
    if search:
        articles = [article_obj for article_obj in articles if article_matches_search(article_obj, search)]
    article_links = {article_obj.id: article_public_url(article_obj) for article_obj in articles}

    return render_template(
        'dashboard_articles.html',
        articles=articles,
        article_links=article_links,
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
    if article_has_tag(article_obj, static_page_tag('about-us')):
        return redirect(url_for('about'))
    return render_article_page(article_obj)
