from datetime import datetime

from models import User, db


INITIAL_USERS = [
    ("MainAdmin", "MainAdmin@quack.sk", "admin", "Admin67n01"),
    ("TadeasNevrela", "TadeasNevrela@s.zochova.sk", "user", "123456"),
]


def _build_user(username: str, email: str, role: str, password: str) -> User:
    user = User(
        username=username,
        email=email,
        created_at=datetime.utcnow(),
        role=role,
    )
    user.set_password(password)
    return user


def seed_admin():
    """Only creates required initial users when they do not already exist."""
    created = 0
    for username, email, role, password in INITIAL_USERS:
        exists = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if exists:
            continue

        db.session.add(_build_user(username, email, role, password))
        created += 1

    if created:
        db.session.commit()
