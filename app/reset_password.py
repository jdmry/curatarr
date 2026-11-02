"""Set a new admin password from the command line, for when it is forgotten:

    docker exec -it curatarr python -m app.reset_password
"""

import getpass
import sys

from app import auth
from app.branding import APP_SLUG
from app.config import load_env
from app.db import connection, migrate


def main() -> int:
    env = load_env()
    path = env.data_dir / f"{APP_SLUG}.db"
    migrate(path)
    with connection(path) as conn:
        admin = auth.get_admin(conn)
        current = admin.username if admin else ""
        username = input(f"Username [{current}]: ").strip() or current
        if not username:
            print("A username is needed.")
            return 1
        password = getpass.getpass("New password: ")
        problem = auth.password_problem(password)
        if problem:
            print(problem)
            return 1
        if getpass.getpass("Again: ") != password:
            print("The passwords don't match.")
            return 1
        auth.save_admin(conn, username, password)
        auth.end_sessions(conn)  # every browser logs in again
    print("Saved. Log in with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
