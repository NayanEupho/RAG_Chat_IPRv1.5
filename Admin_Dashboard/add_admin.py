from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.admin.auth import add_admin_user, list_admin_users, remove_admin_user  # noqa: E402
from backend.admin.db import init_admin_db  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage simple RAG admin dashboard users.")
    subcommands = parser.add_subparsers(dest="command")

    add_parser = subcommands.add_parser("add", help="Add or update an admin user")
    add_parser.add_argument("email", help="Admin email")
    add_parser.add_argument("password", nargs="?", help="Admin password. If omitted, you will be prompted.")

    subcommands.add_parser("list", help="List admin users")

    remove_parser = subcommands.add_parser("remove", help="Remove an admin user")
    remove_parser.add_argument("email", help="Admin email")

    return parser


def _prompt_email() -> str:
    return input("Admin email: ").strip()


def _add_interactive() -> None:
    email = _prompt_email()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.")
        return
    user = add_admin_user(email, password)
    print(f"Admin saved: {user['email']}")


def _list_interactive() -> None:
    users = list_admin_users()
    if not users:
        print("No admin users found.")
        return
    print("\nAdmin users")
    print("-" * 64)
    for user in users:
        print(f"{user['email']}  created={user['created_at']}  updated={user['updated_at']}")


def _remove_interactive() -> None:
    email = _prompt_email()
    if not email:
        print("Email is required.")
        return
    confirm = input(f"Remove {email.strip().lower()}? Type yes to confirm: ").strip().lower()
    if confirm != "yes":
        print("Remove cancelled.")
        return
    removed = remove_admin_user(email)
    print(f"Removed: {email.strip().lower()}" if removed else f"Admin not found: {email.strip().lower()}")


def interactive_shell() -> int:
    init_admin_db()
    print("RAG Admin user manager")
    print("Commands: add, list, remove, quit")
    while True:
        choice = input("\nadmin-users> ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            print("Done.")
            return 0
        if choice in {"a", "add"}:
            _add_interactive()
        elif choice in {"l", "list"}:
            _list_interactive()
        elif choice in {"r", "remove", "delete"}:
            _remove_interactive()
        elif not choice:
            continue
        else:
            print("Unknown command. Use add, list, remove, or quit.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        return interactive_shell()
    init_admin_db()

    if args.command == "add":
        password = args.password
        if password is None:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords do not match.", file=sys.stderr)
                return 2
        user = add_admin_user(args.email, password)
        print(f"Admin saved: {user['email']}")
        return 0

    if args.command == "list":
        users = list_admin_users()
        if not users:
            print("No admin users found.")
            return 0
        for user in users:
            print(f"{user['email']}  created={user['created_at']}  updated={user['updated_at']}")
        return 0

    if args.command == "remove":
        removed = remove_admin_user(args.email)
        print(f"Removed: {args.email.strip().lower()}" if removed else f"Admin not found: {args.email.strip().lower()}")
        return 0 if removed else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
