"""Initial data seeding for local Quack Wiki installs."""

from datetime import datetime
import os

from models import User, db


def _build_user(username: str, email: str, role: str, password: str) -> User:
    """Create a User object with a hashed password ready for insertion."""
    user = User(
        username=username,
        email=email,
        created_at=datetime.utcnow(),
        role=role,
    )
    user.set_password(password)
    return user


def seed_admin():
    """Create an initial admin only when configured through environment variables."""
    password = os.environ.get('INITIAL_ADMIN_PASSWORD')
    if not password:
        return

    username = os.environ.get('INITIAL_ADMIN_USERNAME', 'MainAdmin')
    email = os.environ.get('INITIAL_ADMIN_EMAIL', 'admin@example.com')
    exists = User.query.filter(
        (User.username == username) | (User.email == email)
    ).first()
    if not exists:
        db.session.add(_build_user(username, email, 'admin', password))
        db.session.commit()
