from datetime import datetime

from models import Article, User, db


def _build_user(username: str, email: str, role: str, password: str) -> User:
    user = User(
        username=username,
        email=email,
        created_at=datetime.utcnow(),
        role=role,
    )
    user.set_password(password)
    return user


def seed_dummy_users() -> int:
    """Insert deterministic dummy users (idempotent)."""
    dummy_specs = [
        ("duck_user_01", "duck_user_01@quack.sk", "user"),
        ("duck_user_02", "duck_user_02@quack.sk", "user"),
        ("duck_user_03", "duck_user_03@quack.sk", "user"),
        ("duck_user_04", "duck_user_04@quack.sk", "user"),
        ("duck_user_05", "duck_user_05@quack.sk", "user"),
        ("duck_writer_01", "duck_writer_01@quack.sk", "writer"),
        ("duck_writer_02", "duck_writer_02@quack.sk", "writer"),
        ("duck_writer_03", "duck_writer_03@quack.sk", "writer"),
    ]
    for i in range(6, 26):
        dummy_specs.append((f"duck_user_{i:02d}", f"duck_user_{i:02d}@quack.sk", "user"))
    for i in range(4, 9):
        dummy_specs.append((f"duck_writer_{i:02d}", f"duck_writer_{i:02d}@quack.sk", "writer"))

    created = 0
    for username, email, role in dummy_specs:
        exists = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if exists:
            continue
        db.session.add(_build_user(username, email, role, "123456789"))
        created += 1

    return created


def seed_admin():
    pages = []
    if User.query.filter_by(role="admin").count() == 0:
        pages.append(_build_user("MainAdmin", "MainAdmin@quack.sk", "admin", "Admin67n01"))

    if User.query.filter_by(email="TadeasNevrela@s.zochova.sk").count() == 0:
        pages.append(_build_user("TadeasNevrela", "TadeasNevrela@s.zochova.sk", "user", "123456"))

    if Article.query.filter_by(title="About-Us").count() < 1:
        pages.append(
            Article(
                title="About-Us",
                author="Tadeas Nevrela",
                created_at=datetime.utcnow(),
                image_url="default.png",
                summary="An introduction of our team and our goals with this project.",
                content="To be added",
                tags=["about us"],
            )
        )

    if pages:
        db.session.add_all(pages)

    created_dummy = seed_dummy_users()
    db.session.commit()
    print(f"Seed complete. Dummy users added: {created_dummy}")
