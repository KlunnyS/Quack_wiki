from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin


db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(30), default='user')
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), unique=True, nullable=False)
    author = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image_url = db.Column(db.String(120), default='default.png')
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    tags = db.Column(db.JSON, default=list)
    status = db.Column(db.String(20), default='pending', nullable=False)
    approved_by = db.Column(db.String(120), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)
