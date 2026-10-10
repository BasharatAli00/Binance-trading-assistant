import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import AdminUser
import bcrypt
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL found in .env")
    exit(1)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Check if admin user exists
user = session.query(AdminUser).filter(AdminUser.username == "admin").first()
new_password = "password123"
hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

if user:
    user.password_hash = hashed
    print("Updated existing 'admin' user password to 'password123'")
else:
    new_user = AdminUser(username="admin", password_hash=hashed)
    session.add(new_user)
    print("Created new 'admin' user with password 'password123'")

session.commit()
session.close()
