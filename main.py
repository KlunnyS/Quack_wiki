"""Main Flask application for Quack Wiki.

This module owns app setup, public routes, dashboard routes, article rendering,
file uploads, and small compatibility migrations for the SQLite database.
"""

from datetime import datetime
import html
import os
import re
import unicodedata
from urllib.parse import urlparse, urljoin
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from uuid import uuid4

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import text
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

from forms import ArticleForm, LoginForm, PasswordChangeForm, ProfileForm, RegisterForm, RoleForm, SiteSettingsForm
from models import Article, ArticleRevision, SiteSettings, User, db
from seed import seed_admin

MAX_UPLOAD_SIZE_MB = 50
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ENV = os.environ.get('QUACK_ENV') or os.environ.get('FLASK_ENV') or 'development'
IS_PRODUCTION = APP_ENV.lower() == 'production'


def env_bool(name, default=False):
    """Read a boolean setting from environment variables."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def database_uri():
    """Return the configured database URI, defaulting to the app instance DB."""
    uri = os.environ.get('QUACK_DATABASE_URI') or os.environ.get('DATABASE_URL')
    if uri:
        # Some hosts still expose old-style postgres:// URLs.
        if uri.startswith('postgres://'):
            uri = uri.replace('postgres://', 'postgresql://', 1)
        return uri
    return 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'pages.db')


def secret_key():
    """Require an explicit secret in production; use a local-only fallback otherwise."""
    key = os.environ.get('QUACK_SECRET_KEY') or os.environ.get('SECRET_KEY')
    if key:
        return key
    if IS_PRODUCTION:
        raise RuntimeError('Set QUACK_SECRET_KEY before running Quack Wiki in production.')
    return 'dev-only-change-me'

app = Flask(__name__)
app.config['SECRET_KEY'] = secret_key()
app.config['SQLALCHEMY_DATABASE_URI'] = database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE_BYTES
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'img', 'upload')
app.config['PROFILE_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'img', 'profile')
app.config['SITE_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'img', 'site')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = env_bool('QUACK_SESSION_COOKIE_SECURE', IS_PRODUCTION)
app.config['PREFERRED_URL_SCHEME'] = 'https' if IS_PRODUCTION else 'http'

db.init_app(app)


# --- Startup and maintenance helpers ---

def cleanup_unused_images():
    """Remove uploaded image files that are no longer referenced by the database."""
    # Build the set of database paths that are still in use before touching disk.
    referenced_paths = {
        image_path
        for image_path, in db.session.query(Article.image_url).filter(Article.image_url.isnot(None)).all()
    }
    referenced_paths.update(
        image_path
        for image_path, in db.session.query(ArticleRevision.image_url).filter(ArticleRevision.image_url.isnot(None)).all()
    )
    referenced_paths.update(
        image_path
        for image_path, in db.session.query(User.profile_image_url).filter(User.profile_image_url.isnot(None)).all()
    )
    referenced_paths.update(
        image_path
        for image_path, in db.session.query(SiteSettings.hero_image_url).filter(SiteSettings.hero_image_url.isnot(None)).all()
    )
    referenced_paths.discard('default.png')

    # Database values are stored as paths relative to static/img, grouped by upload type.
    managed_dirs = {
        'upload': app.config['UPLOAD_FOLDER'],
        'profile': app.config['PROFILE_UPLOAD_FOLDER'],
        'site': app.config['SITE_UPLOAD_FOLDER'],
    }
    for folder_key, folder_path in managed_dirs.items():
        if not os.path.isdir(folder_path):
            continue
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if not os.path.isfile(file_path):
                continue
            if f"{folder_key}/{filename}" not in referenced_paths:
                os.remove(file_path)


def ensure_user_profile_columns():
    """Add profile columns to older SQLite databases created before profiles existed."""
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        return

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
    """Return the singleton site settings row, creating it on first run."""
    settings = SiteSettings.query.get(1)
    if not settings:
        settings = SiteSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


with app.app_context():
    # Startup bootstrap: create tables/folders and guarantee required seed data exists.
    db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['PROFILE_UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['SITE_UPLOAD_FOLDER'], exist_ok=True)
    ensure_user_profile_columns()
    get_site_settings()
    if not IS_PRODUCTION or env_bool('QUACK_SEED_INITIAL_USERS'):
        seed_admin()
    cleanup_unused_images()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# --- Request-wide handlers and authorization helpers ---

@app.errorhandler(RequestEntityTooLarge)
def handle_upload_too_large(error):
    """Show a friendly message when an upload exceeds the global request limit."""
    flash(f'Upload is too large. Maximum file size is {MAX_UPLOAD_SIZE_MB} MB.', 'danger')
    return redirect(request.referrer or url_for('index'))


@app.route('/healthz')
def healthz():
    """Lightweight deployment health check."""
    return 'ok', 200


@app.context_processor
def inject_site_settings():
    """Expose site-wide settings and lightweight dashboard counters to templates."""
    pending_counts = {'pending_articles': 0, 'pending_updates': 0}
    if current_user.is_authenticated and current_user.role in ['admin', 'writer']:
        # Sidebar badges should only count actionable article-management work.
        pending_counts = {
            'pending_articles': Article.query.filter(
                Article.is_archived.is_(False),
                func.lower(func.trim(Article.status)) == 'pending',
            ).count(),
            'pending_updates': ArticleRevision.query.filter_by(status='pending').count(),
        }
    return {'site_settings': get_site_settings(), 'dashboard_pending_counts': pending_counts}


@login_manager.user_loader
def load_user(user_id):
    """Load active users for Flask-Login sessions."""
    user = User.query.get(int(user_id))
    if user and user.is_archived:
        return None
    return user


def role_required(role_names: list):
    """Route decorator for pages that require one of the provided roles."""
    def decorator(func):
        @wraps(func)
        @login_required
        def wrapper(*args, **kwargs):
            # Flask-Login guarantees a user exists here; this check enforces the allowed roles.
            if current_user.role not in role_names:
                abort(403)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def is_safe_redirect_url(target):
    """Allow only local redirects to prevent open redirect bugs."""
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ('http', 'https') and redirect_url.netloc == host_url.netloc


def safe_next_url(default_endpoint='index'):
    """Resolve a local next URL from query/form values or fall back to an endpoint."""
    target = request.values.get('next')
    if is_safe_redirect_url(target):
        return target
    return url_for(default_endpoint)


def dashboard_return_url(default_endpoint):
    """Return to the current dashboard filter page after POST actions when safe."""
    target = request.form.get('next') or request.referrer
    if is_safe_redirect_url(target):
        return target
    return url_for(default_endpoint)


# --- Safe limited markdown rendering ---

def _inline_markdown(text: str) -> str:
    """Render the small inline markdown subset used in article content."""
    code_spans = []

    def stash_code(match):
        # Code text is escaped before the full line is escaped, then restored later.
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
    """Render a safe, limited markdown subset without accepting raw HTML."""
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
        """Close any open list before switching to another block type."""
        nonlocal in_ul, in_ol
        if in_ul:
            blocks.append('</ul>')
            in_ul = False
        if in_ol:
            blocks.append('</ol>')
            in_ol = False

    def flush_paragraph():
        """Render buffered normal text as one paragraph."""
        if paragraph:
            blocks.append(f"<p>{_inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_code():
        """Render collected fenced-code lines without parsing markdown inside them."""
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


# --- Article identity, visibility, search, and reserved pages ---

def article_public_url(article_obj: Article) -> str:
    """Resolve the public URL for normal articles and reserved static-page tags."""
    if article_has_tag(article_obj, static_page_tag('about-us')):
        return url_for('about')
    return url_for('article', article_title=article_obj.title)


def normalize_identity(value: str) -> str:
    """Normalize names for matching legacy article authors to current users."""
    ascii_value = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '', ascii_value.lower())


def find_user_for_article_author(author_name: str):
    """Resolve exact usernames and older display-name author values to active users."""
    if not author_name:
        return None

    exact_user = User.query.filter_by(username=author_name).first()
    if exact_user:
        return None if exact_user.is_archived else exact_user

    normalized_author = normalize_identity(author_name)
    if not normalized_author:
        return None

    active_users = User.query.filter(User.is_archived.is_(False)).all()
    return next(
        (
            user
            for user in active_users
            if normalized_author in {
                normalize_identity(user.username),
                normalize_identity(user.public_display_name),
            }
        ),
        None,
    )


def article_is_public(article_obj: Article) -> bool:
    """Public articles must be approved, not archived, and written by an active user."""
    if not article_obj or article_obj.is_archived or article_obj.status != 'approved':
        return False
    return bool(find_user_for_article_author(article_obj.author))


def can_open_article(article_obj: Article) -> bool:
    """Return whether an anonymous/public request may open the article page."""
    return article_is_public(article_obj)


def static_page_tag(page_key: str) -> str:
    """Normalize a named static page into its reserved article tag."""
    return f"page:{page_key.strip().lower()}"


def article_has_tag(article_obj: Article, tag_name: str) -> bool:
    """Case-insensitive tag lookup for article tag lists."""
    wanted = tag_name.strip().lower()
    return any(str(tag).strip().lower() == wanted for tag in (article_obj.tags or []))


def tag_search_needle(search: str):
    """Return normalized tag name when search uses #tag syntax."""
    needle = search.strip().lower()
    if not needle.startswith('#'):
        return None
    return needle[1:].strip()


def article_matches_search(article_obj: Article, search: str) -> bool:
    """Match article search against public article fields and tags."""
    needle = search.strip().lower()
    if not needle:
        return True

    tag_needle = tag_search_needle(search)
    tags = [str(tag).strip().lower() for tag in (article_obj.tags or [])]
    if tag_needle is not None:
        # Queries like "#lore" intentionally search tags only, not title/summary text.
        return bool(tag_needle) and any(tag_needle in tag for tag in tags)

    fields = [
        article_obj.title or '',
        article_obj.summary or '',
        article_obj.author or '',
    ]
    return any(needle in value.lower() for value in fields + tags)


def user_matches_public_search(user: User, search: str) -> bool:
    """Match account search against public fields only; email stays private."""
    needle = search.strip().lower()
    if not needle:
        return True

    fields = [
        user.username or '',
        user.public_display_name or '',
        user.public_bio or '',
        user.role or '',
    ]
    return any(needle in value.lower() for value in fields)


def active_users_by_username(usernames):
    """Return only non-archived users from a username collection."""
    resolved_users = {}
    for username in {username for username in usernames if username}:
        user = find_user_for_article_author(username)
        if user:
            resolved_users[username] = user
    return resolved_users


def public_articles_for_user(user: User):
    """Return public articles whose author field resolves to the given user."""
    candidates = Article.query.filter(
        Article.is_archived.is_(False),
        func.lower(func.trim(Article.status)) == 'approved',
    ).order_by(Article.created_at.desc()).all()
    return [
        article_obj
        for article_obj in candidates
        if (resolved_user := find_user_for_article_author(article_obj.author)) and resolved_user.id == user.id
    ]


def published_article_counts_by_user():
    """Count public articles by resolved active user instead of raw author text."""
    counts = {}
    candidates = Article.query.filter(
        Article.is_archived.is_(False),
        func.lower(func.trim(Article.status)) == 'approved',
    ).all()
    for article_obj in candidates:
        user = find_user_for_article_author(article_obj.author)
        if user:
            counts[user.username] = counts.get(user.username, 0) + 1
    return counts


def revision_matches_search(revision: ArticleRevision, search: str) -> bool:
    """Match dashboard revision search against revision metadata and tags."""
    needle = search.strip().lower()
    if not needle:
        return True

    tag_needle = tag_search_needle(search)
    tags = [str(tag).strip().lower() for tag in (revision.tags or [])]
    if tag_needle is not None:
        # Keep pending-update search behavior consistent with public article #tag search.
        return bool(tag_needle) and any(tag_needle in tag for tag in tags)

    fields = [
        revision.article.title if revision.article else '',
        revision.title or '',
        revision.summary or '',
        revision.editor or '',
    ]
    return any(needle in value.lower() for value in fields + tags)


def find_published_article_by_tag(tag_name: str):
    """Find the newest public article that owns a reserved page tag."""
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
    """Normalize comma-separated tags and protect reserved page:* tags."""
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
    """Apply edit permissions for admins, writers, and article owners."""
    if not current_user.is_authenticated:
        return False
    if article_obj.is_archived:
        return False
    # Writers are trusted contributors: they can edit articles, but non-admin edits are stored as revisions.
    if current_user.role in ['admin', 'writer']:
        return True
    return article_obj.author == current_user.username


# --- Upload, revision, and rendering helpers ---

def parse_infobox_data(raw_data: str):
    """Parse simple 'Label: Value' lines into infobox rows."""
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
    """Store an uploaded article image and return its static/img-relative path."""
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
    """Store an uploaded profile image and return its static/img-relative path."""
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
    """Store an uploaded site image and return its static/img-relative path."""
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
    """Keep article ownership and approval references valid after username edits."""
    if old_username == new_username:
        return

    Article.query.filter_by(author=old_username).update({'author': new_username})
    Article.query.filter_by(approved_by=old_username).update({'approved_by': new_username})
    ArticleRevision.query.filter_by(editor=old_username).update({'editor': new_username})


def save_or_replace_pending_revision(article_obj, form, parsed_tags, image_path):
    """Keep a single pending revision per article until review."""
    # Replacing the open pending revision prevents stacked unreviewed edits for one article.
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
    """Promote a pending revision into the live article record."""
    article_obj = revision.article
    # The revision is the reviewed source of truth; copy it onto the live article row.
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
    """Build all derived data needed by the public article template."""
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
        author_user=find_user_for_article_author(article_obj.author),
        rendered_content=rendered_content,
        infobox_rows=infobox_rows,
        article_link=article_public_url(article_obj),
        can_edit=can_edit_article(article_obj),
        pending_revision=pending_revision,
    )


# --- Authentication and profile routes ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Create a new active account after validating unique email and username."""
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
    """Authenticate active users by email and password."""
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
            return redirect(safe_next_url())

    return render_template('auth/login.html', form=form, error=error)


@app.route('/logout')
@login_required
def logout():
    """End the current Flask-Login session."""
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Let users edit public profile details or change their password."""
    profile_form = ProfileForm(obj=current_user)
    password_form = PasswordChangeForm()

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'profile':
            # Recreate the form from submitted data so validation errors reflect the POST payload.
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


# --- User pages and public browsing routes ---

@app.route('/my-pages')
@login_required
def my_pages():
    """Show the current user's articles with local filters and sorting."""
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


@app.route('/authors')
def authors():
    """Search public accounts; direct browsing shows only published authors."""
    search = (request.args.get('q') or '').strip()
    include_all_users = request.args.get('all') == '1'
    published_counts = published_article_counts_by_user()

    public_users_query = User.query.filter(User.is_archived.is_(False))
    if not include_all_users:
        public_users_query = public_users_query.filter(User.username.in_(list(published_counts.keys())))

    public_users = public_users_query.order_by(User.username.asc()).all()
    if search:
        public_users = [user for user in public_users if user_matches_public_search(user, search)]

    return render_template(
        'authors.html',
        users=public_users,
        published_counts=published_counts,
        search=search,
        include_all_users=include_all_users,
    )


@app.route('/authors/<username>')
def public_profile(username):
    """Display one active user's public profile and approved articles."""
    user = User.query.filter_by(username=username).first_or_404()
    if user.is_archived:
        abort(404)
    articles = public_articles_for_user(user)
    article_links = {article_obj.id: article_public_url(article_obj) for article_obj in articles}
    return render_template(
        'public_profile.html',
        profile_user=user,
        articles=articles,
        article_links=article_links,
    )


@app.route('/')
def index():
    """Render the home page."""
    return render_template('index.html')


@app.route('/search')
def site_search():
    """Navbar search router: @queries search accounts, all others search articles."""
    search = (request.args.get('q') or '').strip()
    if search.startswith('@'):
        # @username searches intentionally include users without published articles.
        return redirect(url_for('authors', q=search[1:].strip(), all='1'))
    return redirect(url_for('articles', q=search))


@app.route('/about')
def about():
    """Render the reserved About page if its backing article is published."""
    about_article = find_published_article_by_tag('about-us')
    if about_article:
        return render_article_page(about_article)
    flash('About article is not published yet.', 'info')
    return redirect(url_for('index'))


@app.route('/wiki/<tag>')
def tagged_article(tag):
    """Render a reserved tag-backed page such as levels, weapons, or lore."""
    article_obj = find_published_article_by_tag(tag)
    if article_obj:
        return render_article_page(article_obj)
    flash(f'No published article found for tag: {tag}', 'info')
    return redirect(url_for('articles'))


@app.route('/articles')
def articles():
    """Browse approved public articles with optional text search."""
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


# --- Article creation and editing ---

@app.route('/articles/new', methods=['GET', 'POST'])
@login_required
def create_article():
    """Create a new article draft owned by the current user."""
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
            # Database constraints are still the final authority for unique titles and field sizes.
            db.session.add(article_obj)
            db.session.commit()
            flash('Article created successfully.', 'success')
            if article_is_public(article_obj):
                return redirect(article_public_url(article_obj))
            return redirect(url_for('my_pages'))
        except SQLAlchemyError:
            db.session.rollback()
            flash('Could not create article. Check title uniqueness and field lengths.', 'danger')

    return render_template('create_article.html', form=form, is_edit=False, article=None)


@app.route('/articles/<int:article_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_article(article_id):
    """Edit an article directly as admin or submit an update for review."""
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
        remove_current_image = form.remove_image.data and not uploaded_image
        # A new upload wins over removal; otherwise removal resets to the default image.
        if uploaded_image:
            image_path = uploaded_image
        elif remove_current_image:
            image_path = 'default.png'
        else:
            image_path = article_obj.image_url or 'default.png'

        if current_user.role in ['admin', 'writer']:
            # Trusted editors update the live row directly; user edits go through revisions.
            article_obj.title = normalized_title
            article_obj.summary = (form.summary.data or '').strip()
            article_obj.content = form.content.data.strip()
            article_obj.infobox_data = (form.infobox_data.data or '').strip()
            article_obj.image_url = image_path
            article_obj.tags = parsed_tags
            if article_obj.status == 'approved':
                article_obj.approved_by = current_user.username
                article_obj.approved_at = datetime.utcnow()
            if pending_revision:
                db.session.delete(pending_revision)
            flash('Article updated successfully.', 'success')
        else:
            save_or_replace_pending_revision(article_obj, form, parsed_tags, image_path)
            flash('Article updated and sent for approval.', 'info')

        db.session.commit()
        if uploaded_image or remove_current_image:
            cleanup_unused_images()
        if article_is_public(article_obj):
            return redirect(article_public_url(article_obj))
        return redirect(url_for('my_pages'))

    return render_template('create_article.html', form=form, is_edit=True, article=article_obj)


# --- Dashboard pages ---

@app.route('/dashboard')
@role_required(['admin'])
def dashboard():
    """Redirect the generic dashboard URL to the admin user table."""
    return redirect(url_for('dashboard_users'))


@app.route('/dashboard/users')
@role_required(['admin'])
def dashboard_users():
    """Admin view for managing users, roles, and account archive state."""
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
    all_published_counts = published_article_counts_by_user()
    published_counts = {user.username: all_published_counts.get(user.username, 0) for user in users}
    role_form = RoleForm()

    return render_template(
        'dashboard_users.html',
        users=users,
        published_counts=published_counts,
        role_form=role_form,
        search=search,
        role_filter=role_filter,
        show_archived=show_archived,
        sort=sort,
    )


@app.route('/dashboard/articles')
@role_required(['admin', 'writer'])
def dashboard_articles():
    """Reviewer view for searching, approving, and archiving articles."""
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
    # Templates receive prebuilt links because reserved page tags use special URLs.
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
    """Reviewer view for pending article update submissions."""
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
    query = ArticleRevision.query.filter_by(status='pending')
    revisions = query.order_by(sort_map.get(sort, ArticleRevision.created_at.desc())).all()
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
    """Admin settings page for site-wide visual options."""
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
    """Remove the home page banner image from site settings."""
    settings = get_site_settings()
    settings.hero_image_url = None
    db.session.commit()
    flash('Community banner image removed.', 'info')
    return redirect(url_for('dashboard_settings'))


# --- Admin and reviewer actions ---

@app.route('/set-role/<int:user_id>', methods=['POST'])
@role_required(['admin'])
def set_role(user_id):
    """Change a user's role while protecting MainAdmin and admin boundaries."""
    form = RoleForm()

    if form.validate_on_submit():
        user = User.query.get_or_404(user_id)
        # MainAdmin and self-protection rules reduce the chance of locking out all admins.
        if user.username == 'MainAdmin':
            flash('Cannot change MainAdmin role.', 'danger')
            return redirect(dashboard_return_url('dashboard_users'))
        if user.is_archived:
            flash('Cannot change role for archived user.', 'danger')
            return redirect(dashboard_return_url('dashboard_users'))
        if user.id == current_user.id:
            flash('You cannot change your own role.', 'danger')
            return redirect(dashboard_return_url('dashboard_users'))
        admin_role_changed = user.role == 'admin' or form.role.data == 'admin'
        if admin_role_changed and current_user.username != 'MainAdmin':
            flash('Only MainAdmin can add or remove admin role.', 'danger')
            return redirect(dashboard_return_url('dashboard_users'))

        user.role = form.role.data
        db.session.commit()
        flash(f'Role updated for {user.username}.', 'success')

    return redirect(dashboard_return_url('dashboard_users'))


@app.route('/users/<int:user_id>/toggle-archive', methods=['POST'])
@role_required(['admin'])
def toggle_archive_user(user_id):
    """Deactivate or reactivate a user account from the admin dashboard."""
    user = User.query.get_or_404(user_id)
    if user.username == 'MainAdmin':
        flash('Cannot archive MainAdmin.', 'danger')
        return redirect(dashboard_return_url('dashboard_users'))
    if user.id == current_user.id:
        flash('You cannot archive your own account.', 'danger')
        return redirect(dashboard_return_url('dashboard_users'))
    if user.role == 'admin' and current_user.username != 'MainAdmin':
        flash('Only MainAdmin can archive another admin.', 'danger')
        return redirect(dashboard_return_url('dashboard_users'))

    user.is_archived = not user.is_archived
    user.archived_at = datetime.utcnow() if user.is_archived else None
    db.session.commit()
    flash(f"User {'deactivated' if user.is_archived else 'reactivated'}: {user.username}", 'info')
    return redirect(dashboard_return_url('dashboard_users'))


@app.route('/approve/<int:article_id>', methods=['POST'])
@role_required(['admin', 'writer'])
def approve(article_id):
    """Approve a new article or apply its latest pending revision."""
    article_obj = Article.query.get_or_404(article_id)
    if article_obj.is_archived:
        flash('Cannot approve archived article.', 'danger')
        return redirect(dashboard_return_url('dashboard_articles'))

    pending_revision = ArticleRevision.query.filter_by(
        article_id=article_obj.id,
        status='pending',
    ).order_by(ArticleRevision.created_at.desc()).first()
    if pending_revision:
        # If a declined/pending article has an update, approval applies that reviewed revision.
        apply_revision(pending_revision)
    else:
        article_obj.status = 'approved'
        article_obj.approved_by = current_user.username
        article_obj.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f'Approved article: {article_obj.title}', 'success')
    return redirect(dashboard_return_url('dashboard_articles'))


@app.route('/decline/<int:article_id>', methods=['POST'])
@role_required(['admin', 'writer'])
def decline(article_id):
    """Mark an article submission as declined."""
    article_obj = Article.query.get_or_404(article_id)
    if article_obj.is_archived:
        flash('Cannot decline archived article.', 'danger')
        return redirect(dashboard_return_url('dashboard_articles'))

    article_obj.status = 'declined'
    article_obj.approved_by = current_user.username
    article_obj.approved_at = datetime.utcnow()
    db.session.commit()
    flash('Article declined.', 'warning')
    return redirect(dashboard_return_url('dashboard_articles'))


@app.route('/revisions/<int:revision_id>/approve', methods=['POST'])
@role_required(['admin', 'writer'])
def approve_revision(revision_id):
    """Approve one pending revision after checking title uniqueness."""
    revision = ArticleRevision.query.get_or_404(revision_id)
    duplicate = Article.query.filter(
        Article.title == revision.title,
        Article.id != revision.article_id,
    ).first()
    if duplicate:
        flash('Cannot approve update because another article already uses that title.', 'danger')
        return redirect(dashboard_return_url('dashboard_updates'))

    article_obj = apply_revision(revision)
    db.session.commit()
    flash(f'Approved update for article: {article_obj.title}', 'success')
    return redirect(dashboard_return_url('dashboard_updates'))


@app.route('/revisions/<int:revision_id>/decline', methods=['POST'])
@role_required(['admin', 'writer'])
def decline_revision(revision_id):
    """Delete a pending revision without changing the live article."""
    revision = ArticleRevision.query.get_or_404(revision_id)
    title = revision.article.title
    db.session.delete(revision)
    db.session.commit()
    flash(f'Discarded pending update for article: {title}', 'warning')
    return redirect(dashboard_return_url('dashboard_updates'))


@app.route('/articles/<int:article_id>/toggle-archive', methods=['POST'])
@role_required(['admin', 'writer'])
def toggle_archive_article(article_id):
    """Archive or restore any article from the reviewer dashboard."""
    article_obj = Article.query.get_or_404(article_id)
    article_obj.is_archived = not article_obj.is_archived
    article_obj.archived_at = datetime.utcnow() if article_obj.is_archived else None
    db.session.commit()
    flash(f"Article {'archived' if article_obj.is_archived else 'restored'}: {article_obj.title}", 'info')
    return redirect(dashboard_return_url('dashboard_articles'))


@app.route('/articles/<int:article_id>/archive-own', methods=['POST'])
@login_required
def archive_own_article(article_id):
    """Let article owners archive or restore their own articles."""
    article_obj = Article.query.get_or_404(article_id)
    if article_obj.author != current_user.username:
        abort(403)

    if not article_obj.is_archived:
        # Pending edits are discarded when the owner hides the article.
        ArticleRevision.query.filter_by(article_id=article_obj.id, status='pending').delete()
    article_obj.is_archived = not article_obj.is_archived
    article_obj.archived_at = datetime.utcnow() if article_obj.is_archived else None
    db.session.commit()
    flash(f"Article {'archived' if article_obj.is_archived else 'restored'}: {article_obj.title}", 'info')
    return redirect(url_for('my_pages'))


# --- Final public article route ---

@app.route('/article/<article_title>')
def article(article_title):
    """Render one public article by title."""
    article_obj = Article.query.filter_by(title=article_title, is_archived=False).first_or_404()
    if not can_open_article(article_obj):
        flash('That article is not public yet.', 'warning')
        return redirect(url_for('articles'))
    if article_has_tag(article_obj, static_page_tag('about-us')):
        return redirect(url_for('about'))
    return render_article_page(article_obj)
