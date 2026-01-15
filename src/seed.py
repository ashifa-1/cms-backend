from database import SessionLocal
from models import User, UserRole
from auth import get_password_hash

db = SessionLocal()
if not db.query(User).filter(User.email == "author@example.com").first():
    test_user = User(
        username="author1",
        email="author@example.com",
        password_hash=get_password_hash("securepassword"),
        role=UserRole.author
    )
    db.add(test_user)
    db.commit()
    print("Test author created!")
db.close()