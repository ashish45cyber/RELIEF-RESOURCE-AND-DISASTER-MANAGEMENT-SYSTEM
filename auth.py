"""Login + role-based access. Passwords are stored salted + hashed (PBKDF2), never in plain text."""
import hashlib
import os
import db

ROLES = ("ADMIN", "DONOR", "STAFF", "AREA_REP")


def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 50_000).hex()


def create_user(username, password, role, ref_id=None):
    if role not in ROLES:
        raise ValueError("Invalid role")
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters")
    salt = os.urandom(16).hex()
    with db.transaction() as c:
        c.execute("INSERT INTO app_user(username,password_hash,salt,role,ref_id) VALUES (?,?,?,?,?)",
                  (username, _hash(password, salt), salt, role, ref_id))


def login(username, password):
    row = db.get_conn().execute("SELECT * FROM app_user WHERE username=?", (username,)).fetchone()
    if row and _hash(password, row["salt"]) == row["password_hash"]:
        return dict(row)
    return None
