from models import User, db, Article
from datetime import datetime

def seed_admin():
    pages = []
    if User.query.filter_by(role="admin").count() > 0:
        print("Admin uz v databaze existuju – Admin add sa preskakuje.")
    else:
        pages.append(
            User(
                username = "MainAdmin",
                email = "MainAdmin@quack.sk",
                password_hash = "scrypt:32768:8:1$r3vO2Vswin8lxB8h$ab0dc99f5963e3e281185e3211227bcbc9e5169f2d29f4b98363600b8e0319b68391ef5af706d609fe42b4f07b44cbddb126ef991d6e138292feb2d0e361747f", #Admin67n01
                created_at = datetime.utcnow(),
                role = "admin"
            ),
            User(
                username = "TadeasNevrela",
                email = "TadeasNevrela@s.zochova.sk",
                password_hash = "scrypt:32768:8:1$AV1CPk8lcdZ23jhx$e5a4bfb54348414ea0dd0b0081c985656b7af29540b4b164f5224cedb5eb8462ece56ebef4fb552ee47acc71c8c553a00c42112e8353689258b551fe8cdcffa1", #123456
                created_at = datetime.utcnow(),
                role = "user"
            )
        )

    if Article.query.filter_by(title="About-Us").count() < 1:    
        print("No article - Adding About-us")
        pages.append(
            Article(
                title = "About-Us",
                author = "Tadeáš Nevřela",
                created_at = datetime.utcnow(),
                image_url = "default.png",
                summary = "An introduction of our team and our goals with this project.",
                content = "To be added",
                tags = ["about us"]
                )
        )



    db.session.add_all(pages)
    db.session.commit()
    print("Do databazy bol pridaný admin.")