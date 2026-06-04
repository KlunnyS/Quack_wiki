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
from sqlalchemy import text
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

from forms import ArticleForm, LoginForm, PasswordChangeForm, ProfileForm, RegisterForm, RoleForm, SiteSettingsForm
from models import Article, ArticleRevision, SiteSettings, User, db
from seed import seed_admin

app = Flask(__name__)
app.config['SECRET_KEY'] = '#K0nMykvNSC3OyQcA'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pages.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/img/upload'
app.config['PROFILE_UPLOAD_FOLDER'] = 'static/img/profile'
app.config['SITE_UPLOAD_FOLDER'] = 'static/img/site'

db.init_app(app)


def ensure_user_profile_columns():
    columns = db.session.execute(text("PRAGMA table_info(user)")).fetchall()
    column_names = {column[1] for column in columns}
    if 'profile_image_url' not in column_names:
        db.session.execute(text("ALTER TABLE user ADD COLUMN profile_image_url VARCHAR(120)"))
    if 'public_display_name' not in column_names:
        db.session.execute(text("ALTER TABLE user ADD COLUMN public_display_name VARCHAR(80)"))
    if 'public_bio' not in column_names:
        db.session.execute(text("ALTER TABLE user ADD COLUMN public_bio TEXT"))
    if {'profile_image_url', 'public_display_name', 'public_bio'} - column_names:
        db.session.commit()


def get_site_settings():
    settings = SiteSettings.query.get(1)
    if not settings:
        settings = SiteSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


with app.app_context():
    db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['PROFILE_UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['SITE_UPLOAD_FOLDER'], exist_ok=True)
    ensure_user_profile_columns()
    get_site_settings()
    seed_admin()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@app.context_processor
def inject_site_settings():
    return {'site_settings': get_site_settings()}


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    if user and user.is_archived:
        return None
    return user


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
    code_spans = []

    def stash_code(match):
        code_spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"@@CODE{len(code_spans) - 1}@@"

    text = re.sub(r'`([^`]+)`', stash_code, text)
    text = html.escape(text)
    text = re.sub(
        r'\[([^\]]+)\]\((https?://[^\s)]+)\)',
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)

    for index, code_html in enumerate(code_spans):
        text = text.replace(f"@@CODE{index}@@", code_html)
    return text


def render_simple_markdown(raw_text: str) -> str:
    if not raw_text:
        return '<p>No content yet.</p>'

    text = raw_text.replace('\r\n', '\n').replace('\r', '\n').strip()
    lines = text.splitlines()
    blocks = []
    paragraph = []
    in_ul = False
    in_ol = False
    in_code = False
    code_lines = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            blocks.append('</ul>')
            in_ul = False
        if in_ol:
            blocks.append('</ol>')
            in_ol = False

    def flush_paragraph():
        if paragraph:
            blocks.append(f"<p>{_inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_code():
        if code_lines:
            code_text = '\n'.join(code_lines)
            blocks.append(f"<pre><code>{html.escape(code_text)}</code></pre>")
            code_lines.clear()

    for line in lines:
        stripped = line.strip()

        if stripped.startswith('```'):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                close_lists()
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            close_lists()
            continue

        heading = re.match(r'^(#{1,6})\s*(.+)$', stripped)
        if heading:
            flush_paragraph()
            close_lists()
            level = min(len(heading.group(1)), 6)
            blocks.append(f"<h{level}>{_inline_markdown(heading.group(2).strip())}</h{level}>")
            continue

        if stripped.startswith('> '):
            flush_paragraph()
            close_lists()
            blocks.append(f"<blockquote><p>{_inline_markdown(stripped[2:].strip())}</p></blockquote>")
            continue

        if re.match(r'^\d+\.\s+', stripped):
            flush_paragraph()
            if in_ul:
                blocks.append('</ul>')
                in_ul = False
            if not in_ol:
                blocks.append('<ol>')
                in_ol = True
            item = re.sub(r'^\d+\.\s+', '', stripped)
            blocks.append(f"<li>{_inline_markdown(item)}</li>")
            continue

        if re.match(r'^[-*+]\s+', stripped):
            flush_paragraph()
            if in_ol:
                blocks.append('</ol>')
                in_ol = False
            if not in_ul:
                blocks.append('<ul>')
                in_ul = True
            item = re.sub(r'^[-*+]\s+', '', stripped)
            blocks.append(f"<li>{_inline_markdown(item)}</li>")
            continue

        close_lists()
        paragraph.append(stripped)

    if in_code:
        flush_code()
    flush_paragraph()
    close_lists()
    return '\n'.join(blocks)


def article_public_url(article_obj: Article) -> str:
    if article_has_tag(article_obj, static_page_tag('about-us')):
        return url_for('about')
    return url_for('article', article_title=article_obj.title)


def article_is_public(article_obj: Article) -> bool:
    if not article_obj or article_obj.is_archived or article_obj.status != 'approved':
        return False
    author = User.query.filter_by(username=article_obj.author).first()
    return bool(author and not author.is_archived)


def can_open_article(article_obj: Article) -> bool:
    return article_is_public(article_obj)


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


def users_by_username(usernames):
    cleaned_usernames = {username for username in usernames if username}
    if not cleaned_usernames:
        return {}
    users = User.query.filter(User.username.in_(cleaned_usernames)).all()
    return {user.username: user for user in users}


def active_users_by_username(usernames):
    return {
        username: user
        for username, user in users_by_username(usernames).items()
        if not user.is_archived
    }


def revision_matches_search(revision: ArticleRevision, search: str) -> bool:
    needle = search.strip().lower()
    if not needle:
        return True

    fields = [
        revision.article.title if revision.article else '',
        revision.title or '',
        revision.summary or '',
        revision.editor or '',
    ]
    tags = [str(tag) for tag in (revision.tags or [])]
    return any(needle in value.lower() for value in fields + tags)


def find_published_article_by_tag(tag_name: str):
    page_tag = static_page_tag(tag_name)
    candidates = Article.query.filter(
        Article.is_archived.is_(False),
        func.lower(func.trim(Article.status)) == 'approved',
    ).order_by(Article.created_at.desc()).all()
    return next(
        (
            article_obj
            for article_obj in candidates
            if article_is_public(article_obj) and article_has_tag(article_obj, page_tag)
        ),
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
    if article_obj.is_archived:
        return False
    if current_user.role in ['admin', 'writer']:
        return True
    return article_obj.author == current_user.username


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


def save_profile_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None

    safe_name = secure_filename(file_storage.filename)
    if not safe_name:
        return None

    _, ext = os.path.splitext(safe_name)
    filename = f"{uuid4().hex}{ext.lower()}"
    upload_dir = app.config['PROFILE_UPLOAD_FOLDER']
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return f"profile/{filename}"


def save_site_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None

    safe_name = secure_filename(file_storage.filename)
    if not safe_name:
        return None

    _, ext = os.path.splitext(safe_name)
    filename = f"{uuid4().hex}{ext.lower()}"
    upload_dir = app.config['SITE_UPLOAD_FOLDER']
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return f"site/{filename}"


def sync_username_references(old_username: str, new_username: str):
    if old_username == new_username:
        return

    Article.query.filter_by(author=old_username).update({'author': new_username})
    Article.query.filter_by(approved_by=old_username).update({'approved_by': new_username})
    ArticleRevision.query.filter_by(editor=old_username).update({'editor': new_username})


def save_or_replace_pending_revision(article_obj, form, parsed_tags, image_path):
    revision = ArticleRevision.query.filter_by(
        article_id=article_obj.id,
        status='pending',
    ).first()
    if not revision:
        revision = ArticleRevision(article_id=article_obj.id, editor=current_user.username)
        db.session.add(revision)

    revision.editor = current_user.username
    revision.created_at = datetime.utcnow()
    revision.title = form.title.data.strip()
    revision.summary = (form.summary.data or '').strip()
    revision.content = form.content.data.strip()
    revision.infobox_data = (form.infobox_data.data or '').strip()
    revision.image_url = image_path
    revision.tags = parsed_tags
    revision.status = 'pending'
    return revision


def apply_revision(revision):
    article_obj = revision.article
    article_obj.title = revision.title
    article_obj.summary = revision.summary
    article_obj.content = revision.content
    article_obj.infobox_data = revision.infobox_data
    article_obj.image_url = revision.image_url
    article_obj.tags = revision.tags
    article_obj.status = 'approved'
    article_obj.approved_by = current_user.username
    article_obj.approved_at = datetime.utcnow()
    db.session.delete(revision)
    return article_obj


def render_article_page(article_obj: Article):
    rendered_content = render_simple_markdown(article_obj.content)
    infobox_rows = parse_infobox_data(article_obj.infobox_data)
    pending_revision = ArticleRevision.query.filter_by(
        article_id=article_obj.id,
        status='pending',
    ).order_by(ArticleRevision.created_at.desc()).first()
    if not infobox_rows:
        infobox_rows = [
            ('Author', article_obj.author or 'Unknown'),
            ('Created', article_obj.created_at.strftime('%Y-%m-%d') if article_obj.created_at else 'Unknown'),
            ('Status', article_obj.status),
        ]
    return render_template(
        'article.html',
        article=article_obj,
        author_user=User.query.filter_by(username=article_obj.author).first(),
        random_article=None,
        rendered_content=rendered_content,
        infobox_rows=infobox_rows,
        article_link=article_public_url(article_obj),
        can_edit=can_edit_article(article_obj),
        pending_revision=pending_revision,
    )


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        existing_email = User.query.filter_by(email=form.email.data).first()
        existing_username = User.query.filter_by(username=form.username.data.strip()).first()
        if existing_email:
            msg = 'An account with this email already exists.'
            form.email.errors.append(msg)
            flash(msg, 'danger')
        elif existing_username:
            msg = 'This username is already taken.'
            form.username.errors.append(msg)
            flash(msg, 'danger')
        else:
            new_user = User(username=form.username.data.strip(), email=form.email.data)
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
        elif user.is_archived:
            error = 'This account is deactivated.'
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


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    profile_form = ProfileForm(obj=current_user)
    password_form = PasswordChangeForm()

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'profile':
            profile_form = ProfileForm()
            if profile_form.validate_on_submit():
                new_username = profile_form.username.data.strip()
                existing_user = User.query.filter(
                    User.username == new_username,
                    User.id != current_user.id,
                ).first()
                if existing_user:
                    profile_form.username.errors.append('This username is already taken.')
                    flash('This username is already taken.', 'danger')
                else:
                    old_username = current_user.username
                    image_path = save_profile_image(profile_form.profile_image.data)
                    current_user.username = new_username
                    current_user.public_display_name = (profile_form.public_display_name.data or '').strip() or None
                    current_user.public_bio = (profile_form.public_bio.data or '').strip() or None
                    if image_path:
                        current_user.profile_image_url = image_path
                    sync_username_references(old_username, new_username)
                    db.session.commit()
                    flash('Profile updated successfully.', 'success')
                    return redirect(url_for('profile'))

        elif form_type == 'password':
            if password_form.validate_on_submit():
                if not current_user.check_password(password_form.current_password.data):
                    password_form.current_password.errors.append('Current password is incorrect.')
                    flash('Current password is incorrect.', 'danger')
                else:
                    current_user.set_password(password_form.password.data)
                    db.session.commit()
                    flash('Password changed successfully.', 'success')
                    return redirect(url_for('profile'))

    return render_template(
        'profile.html',
        profile_form=profile_form,
        password_form=password_form,
    )


@app.route('/my-pages')
@login_required
def my_pages():
    search = (request.args.get('q') or '').strip()
    status_filter = (request.args.get('status') or 'all').strip().lower()
    show_archived = request.args.get('show_archived') == '1'
    sort = (request.args.get('sort') or 'newest').strip().lower()

    query = Article.query.filter_by(author=current_user.username)
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
    user_articles = query.order_by(sort_map.get(sort, Article.created_at.desc())).all()
    if search:
        user_articles = [article_obj for article_obj in user_articles if article_matches_search(article_obj, search)]

    article_links = {article_obj.id: article_public_url(article_obj) for article_obj in user_articles}
    return render_template(
        'my_pages.html',
        user_articles=user_articles,
        article_links=article_links,
        search=search,
        status_filter=status_filter,
        show_archived=show_archived,
        sort=sort,
    )


@app.route('/authors/<username>')
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user.is_archived:
        abort(404)
    articles = Article.query.filter_by(
        author=user.username,
        status='approved',
        is_archived=False,
    ).order_by(Article.created_at.desc()).all()
    article_links = {article_obj.id: article_public_url(article_obj) for article_obj in articles}
    return render_template(
        'public_profile.html',
        profile_user=user,
        articles=articles,
        article_links=article_links,
    )


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
    article_list = [article_obj for article_obj in article_list if article_is_public(article_obj)]
    if search:
        article_list = [article_obj for article_obj in article_list if article_matches_search(article_obj, search)]
    article_links = {article.id: article_public_url(article) for article in article_list}
    author_users = active_users_by_username(article.author for article in article_list)
    return render_template(
        'articles.html',
        articles=article_list,
        search=search,
        article_links=article_links,
        author_users=author_users,
    )


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
    if article_obj.is_archived:
        flash('Archived articles cannot be edited.', 'warning')
        return redirect(url_for('my_pages') if article_obj.author == current_user.username else url_for('articles'))
    if not can_edit_article(article_obj):
        abort(403)

    pending_revision = ArticleRevision.query.filter_by(
        article_id=article_obj.id,
        status='pending',
    ).order_by(ArticleRevision.created_at.desc()).first()
    form_source = pending_revision or article_obj
    form = ArticleForm(obj=form_source)
    if request.method == 'GET':
        form.tags.data = ', '.join(form_source.tags or [])
        form.infobox_data.data = form_source.infobox_data or ''

    if form.validate_on_submit():
        normalized_title = form.title.data.strip()
        duplicate = Article.query.filter(
            Article.title == normalized_title,
            Article.id != article_obj.id,
        ).first()
        if duplicate:
            flash('Article with this title already exists.', 'danger')
            return render_template('create_article.html', form=form, is_edit=True, article=article_obj)

        uploaded_image = save_article_image(form.image_file.data)
        parsed_tags, removed_reserved = normalize_article_tags(form.tags.data)
        if removed_reserved:
            flash('Reserved page tags can only be used by writers and admins.', 'warning')
        image_path = uploaded_image or article_obj.image_url or 'default.png'

        if current_user.role == 'admin' and article_obj.status == 'approved':
            article_obj.title = normalized_title
            article_obj.summary = (form.summary.data or '').strip()
            article_obj.content = form.content.data.strip()
            article_obj.infobox_data = (form.infobox_data.data or '').strip()
            article_obj.image_url = image_path
            article_obj.tags = parsed_tags
            article_obj.status = 'approved'
            article_obj.approved_by = current_user.username
            article_obj.approved_at = datetime.utcnow()
            flash('Article updated successfully.', 'success')
        else:
            save_or_replace_pending_revision(article_obj, form, parsed_tags, image_path)
            flash('Article updated and sent for approval.', 'info')

        db.session.commit()
        if article_is_public(article_obj):
            return redirect(article_public_url(article_obj))
        return redirect(url_for('my_pages'))

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
    author_users = active_users_by_username(article_obj.author for article_obj in articles)

    return render_template(
        'dashboard_articles.html',
        articles=articles,
        article_links=article_links,
        author_users=author_users,
        search=search,
        status_filter=status_filter,
        show_archived=show_archived,
        sort=sort,
    )


@app.route('/dashboard/updates')
@role_required(['admin', 'writer'])
def dashboard_updates():
    search = (request.args.get('q') or '').strip()
    sort = (request.args.get('sort') or 'newest').strip().lower()

    sort_map = {
        'newest': ArticleRevision.created_at.desc(),
        'oldest': ArticleRevision.created_at.asc(),
        'title_az': ArticleRevision.title.asc(),
        'title_za': ArticleRevision.title.desc(),
        'editor_az': ArticleRevision.editor.asc(),
        'editor_za': ArticleRevision.editor.desc(),
    }
    revisions = ArticleRevision.query.filter_by(status='pending').order_by(
        sort_map.get(sort, ArticleRevision.created_at.desc())
    ).all()
    if search:
        revisions = [revision for revision in revisions if revision_matches_search(revision, search)]

    article_links = {
        revision.article.id: article_public_url(revision.article)
        for revision in revisions
        if revision.article
    }

    return render_template(
        'dashboard_updates.html',
        pending_revisions=revisions,
        article_links=article_links,
        search=search,
        sort=sort,
    )


@app.route('/dashboard/settings', methods=['GET', 'POST'])
@role_required(['admin'])
def dashboard_settings():
    settings = get_site_settings()
    form = SiteSettingsForm()

    if form.validate_on_submit():
        image_path = save_site_image(form.hero_image.data)
        if image_path:
            settings.hero_image_url = image_path
            db.session.commit()
            flash('Community banner image updated.', 'success')
        else:
            flash('Choose an image before saving.', 'warning')
        return redirect(url_for('dashboard_settings'))

    return render_template('dashboard_settings.html', form=form, settings=settings)


@app.route('/dashboard/settings/banner/remove', methods=['POST'])
@role_required(['admin'])
def remove_hero_banner():
    settings = get_site_settings()
    settings.hero_image_url = None
    db.session.commit()
    flash('Community banner image removed.', 'info')
    return redirect(url_for('dashboard_settings'))


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

    pending_revision = ArticleRevision.query.filter_by(
        article_id=article_obj.id,
        status='pending',
    ).order_by(ArticleRevision.created_at.desc()).first()
    if pending_revision:
        apply_revision(pending_revision)
    else:
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


@app.route('/revisions/<int:revision_id>/approve', methods=['POST'])
@role_required(['admin'])
def approve_revision(revision_id):
    revision = ArticleRevision.query.get_or_404(revision_id)
    duplicate = Article.query.filter(
        Article.title == revision.title,
        Article.id != revision.article_id,
    ).first()
    if duplicate:
        flash('Cannot approve update because another article already uses that title.', 'danger')
        return redirect(url_for('dashboard_updates'))

    article_obj = apply_revision(revision)
    db.session.commit()
    flash(f'Approved update for article: {article_obj.title}', 'success')
    return redirect(url_for('dashboard_updates'))


@app.route('/revisions/<int:revision_id>/decline', methods=['POST'])
@role_required(['admin'])
def decline_revision(revision_id):
    revision = ArticleRevision.query.get_or_404(revision_id)
    title = revision.article.title
    db.session.delete(revision)
    db.session.commit()
    flash(f'Discarded pending update for article: {title}', 'warning')
    return redirect(url_for('dashboard_updates'))


@app.route('/articles/<int:article_id>/toggle-archive', methods=['POST'])
@role_required(['admin'])
def toggle_archive_article(article_id):
    article_obj = Article.query.get_or_404(article_id)
    article_obj.is_archived = not article_obj.is_archived
    article_obj.archived_at = datetime.utcnow() if article_obj.is_archived else None
    db.session.commit()
    flash(f"Article {'archived' if article_obj.is_archived else 'restored'}: {article_obj.title}", 'info')
    return redirect(url_for('dashboard_articles'))


@app.route('/articles/<int:article_id>/archive-own', methods=['POST'])
@login_required
def archive_own_article(article_id):
    article_obj = Article.query.get_or_404(article_id)
    if article_obj.author != current_user.username:
        abort(403)

    if not article_obj.is_archived:
        ArticleRevision.query.filter_by(article_id=article_obj.id, status='pending').delete()
    article_obj.is_archived = not article_obj.is_archived
    article_obj.archived_at = datetime.utcnow() if article_obj.is_archived else None
    db.session.commit()
    flash(f"Article {'archived' if article_obj.is_archived else 'restored'}: {article_obj.title}", 'info')
    return redirect(url_for('my_pages'))


@app.route('/article/<article_title>')
def article(article_title):
    article_obj = Article.query.filter_by(title=article_title, is_archived=False).first_or_404()
    if not can_open_article(article_obj):
        flash('That article is not public yet.', 'warning')
        return redirect(url_for('articles'))
    if article_has_tag(article_obj, static_page_tag('about-us')):
        return redirect(url_for('about'))
    return render_article_page(article_obj)
