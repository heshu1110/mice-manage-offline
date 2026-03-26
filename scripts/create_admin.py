from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.main import ensure_schema
from app.models import User
from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update an admin user.")
    parser.add_argument("--name", required=True, help="Admin user name")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--phone", default="", help="Optional phone number")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    ensure_schema()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == args.name.strip()).first()
        if user:
            user.role = "admin"
            user.password_hash = hash_password(args.password)
            user.phone = args.phone.strip() or None
            action = "updated"
        else:
            user = User(
                name=args.name.strip(),
                role="admin",
                phone=args.phone.strip() or None,
                password_hash=hash_password(args.password),
            )
            db.add(user)
            action = "created"
        db.commit()
        print(f"Admin {action}: {user.name}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
