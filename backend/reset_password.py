"""Create or reset the 'admin' dashboard user.

The new password is never hard-coded or printed. It comes from the
ADMIN_NEW_PASSWORD environment variable, or is typed at a hidden prompt.

    python reset_password.py
"""
import getpass
import os
import sys

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import AdminUser

MIN_LENGTH = 12

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL found in .env")
    sys.exit(1)

new_password = os.getenv("ADMIN_NEW_PASSWORD", "")
if not new_password:
    new_password = getpass.getpass("New admin password: ")
    if new_password != getpass.getpass("Repeat it: "):
        print("Passwords do not match. Nothing changed.")
        sys.exit(1)
if len(new_password) < MIN_LENGTH:
    print(f"Password must be at least {MIN_LENGTH} characters. Nothing changed.")
    sys.exit(1)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
user = session.query(AdminUser).filter(AdminUser.username == "admin").first()
if user:
    user.password_hash = hashed
    print("Updated the 'admin' user's password.")
else:
    session.add(AdminUser(username="admin", password_hash=hashed))
    print("Created the 'admin' user.")

session.commit()
session.close()
