import jwt

from app.auth.security import create_access_token, hash_password, verify_password


def test_password_hashing_is_one_way_and_verifiable():
    password = "correct horse battery staple"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong password", hashed)


def test_access_token_contains_identity_roles_and_type():
    token = create_access_token(42, ["visor"])
    payload = jwt.decode(token, options={"verify_signature": False})

    assert payload["sub"] == "42"
    assert payload["roles"] == ["visor"]
    assert payload["type"] == "access"
    assert "exp" in payload
