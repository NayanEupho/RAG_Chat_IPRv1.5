import pytest


def test_xmlsec_binary_env_is_passed_to_pysaml_config(monkeypatch, tmp_path):
    from backend.saml import settings

    xmlsec = tmp_path / "xmlsec1.exe"
    xmlsec.write_text("", encoding="utf-8")

    monkeypatch.setenv("XMLSEC_BINARY", str(xmlsec))
    monkeypatch.delenv("XMLSEC_PATH", raising=False)
    monkeypatch.setattr(settings.SAMLSettings, "idp_cert", lambda self: "CERTDATA")

    cfg = settings.SAMLSettings().pysaml2_config()

    assert cfg["xmlsec_binary"] == str(xmlsec)
    assert "xmlsec_path" not in cfg


def test_xmlsec_path_env_is_passed_to_pysaml_config(monkeypatch, tmp_path):
    from backend.saml import settings

    monkeypatch.delenv("XMLSEC_BINARY", raising=False)
    monkeypatch.setenv("XMLSEC_PATH", str(tmp_path))
    monkeypatch.setattr(settings.SAMLSettings, "idp_cert", lambda self: "CERTDATA")

    cfg = settings.SAMLSettings().pysaml2_config()

    assert cfg["xmlsec_path"] == [str(tmp_path)]
    assert "xmlsec_binary" not in cfg


def test_invalid_xmlsec_binary_fails_with_clear_error(monkeypatch, tmp_path):
    from backend.saml import settings

    missing = tmp_path / "missing-xmlsec.exe"
    monkeypatch.setenv("XMLSEC_BINARY", str(missing))

    with pytest.raises(RuntimeError, match="XMLSEC_BINARY is set but the file does not exist"):
        settings.SAMLSettings()
