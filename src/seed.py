from .database import SessionLocal
from .models import User
from .auth import get_password_hash
from .schemas import UserRole

def seed_data():
    db = SessionLocal()
    # Check if author already exists
    author = db.query(User).filter(User.email == "author@example.com").first()
    if not author:
        new_author = User(
            username="author_user",
            email="author@example.com",
            password_hash=get_password_hash("securepassword"),
            role=UserRole.author
        )
        db.add(new_author)
        db.commit()
        print("Seed: Author created!")
    else:
        print("Seed: Author already exists.")
    db.close()

if __name__ == "__main__":
    seed_data()