import os
import secrets
from functools import lru_cache
from saml2.client import Saml2Client
from saml2.config import Config


class SAMLSettings:
    """
    Holds every env-driven value the SAML package needs:
      - SP / IdP endpoints & cert  (used by pysaml2)
      - Session / JWT config       (used by auth.py)
    """

    def __init__(self):
        # ===== Service Provider (THIS APP) =====
        self.sp_entity_id = os.getenv(
            "SAML_SP_ENTITY_ID",
            "https://askme.ipr.res.in/metadata",
        )
        self.sp_acs_url = os.getenv(
            "SAML_SP_ACS_URL",
            "https://askme.ipr.res.in/saml/acs",
        )

        # ===== Identity Provider (ADFS) =====
        self.idp_entity_id = os.getenv(
            "SAML_IDP_ENTITY_ID",
            "http://adfs.ipr.res.in/adfs/services/trust",
        )
        self.idp_sso_url = os.getenv(
            "SAML_IDP_SSO_URL",
            "https://adfs.ipr.res.in/adfs/ls",
        )
        self.idp_cert_file = os.getenv(
            "SAML_IDP_CERT_FILE",
            "askme.crt",
        )

        # ===== Session / JWT =====
        # In production set SESSION_SECRET to a long random string in .env
        # The fallback generates one per process-start (fine for dev, NOT for
        # multi-worker production – tokens won't survive a restart).
        self.session_secret: str = os.getenv(
            "SESSION_SECRET",
            secrets.token_hex(32),          # 64-char random fallback
        )
        self.session_max_age: int = int(
            os.getenv("SESSION_MAX_AGE", "3600")   # default 1 h
        )
        self.session_cookie_name: str = os.getenv(
            "SESSION_COOKIE_NAME", "saml_session"
        )

    # ------------------------------------------------------------------
    # IdP certificate helpers
    # ------------------------------------------------------------------
    def idp_cert(self) -> str:
        """Load IdP certificate from file."""
        with open(self.idp_cert_file) as f:
            return f.read()

    def idp_metadata_xml(self) -> str:
        """
        Generate SAML IdP metadata XML.
        pysaml2 inline metadata expects a list of XML strings.
        """
        cert_content = self.idp_cert()
        cert_clean = (
            cert_content
            .replace("-----BEGIN CERTIFICATE-----", "")
            .replace("-----END CERTIFICATE-----", "")
        )
        cert_clean = "".join(cert_clean.split())

        return (
            '<?xml version="1.0"?>\n'
            '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"\n'
            f'                  entityID="{self.idp_entity_id}">\n'
            '  <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">\n'
            '    <KeyDescriptor use="signing">\n'
            '      <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">\n'
            '        <X509Data>\n'
            f'          <X509Certificate>{cert_clean}</X509Certificate>\n'
            '        </X509Data>\n'
            '      </KeyInfo>\n'
            '    </KeyDescriptor>\n'
            '    <KeyDescriptor use="encryption">\n'
            '      <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">\n'
            '        <X509Data>\n'
            f'          <X509Certificate>{cert_clean}</X509Certificate>\n'
            '        </X509Data>\n'
            '      </KeyInfo>\n'
            '    </KeyDescriptor>\n'
            f'    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"\n'
            f'                         Location="{self.idp_sso_url}"/>\n'
            f'    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"\n'
            f'                         Location="{self.idp_sso_url}"/>\n'
            '  </IDPSSODescriptor>\n'
            '</EntityDescriptor>'
        )

    # ------------------------------------------------------------------
    # pysaml2 config
    # ------------------------------------------------------------------
    def pysaml2_config(self) -> dict:
        return {
            "entityid": self.sp_entity_id,
            "service": {
                "sp": {
                    "name": "FastAPI SAML SP",
                    "endpoints": {
                        "assertion_consumer_service": [
                            (
                                self.sp_acs_url,
                                "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                            )
                        ],
                    },
                    "allow_unsolicited": True,
                }
            },
            "metadata": {
                "inline": [self.idp_metadata_xml()],
            },
            "security": {
                "want_response_signed": False,
                "want_assertions_signed": False,
                "allow_unsolicited": True,
                "reject_unsigned_assertions": False,
                "reject_unsigned_response": False,
                "validate_certificate": False,
            },
            "attribute_map_dir": None,
        }

    # ------------------------------------------------------------------
    # pysaml2 client
    # ------------------------------------------------------------------
    def get_client(self) -> Saml2Client:
        conf = Config()
        conf.load(self.pysaml2_config())
        conf.allow_unknown_attributes = True
        return Saml2Client(config=conf)


# ======================================================================
# Cached singletons – import these everywhere else in the package
# ======================================================================

@lru_cache()
def get_saml_settings() -> SAMLSettings:
    """Return the one SAMLSettings instance for the whole process."""
    return SAMLSettings()


@lru_cache()
def get_saml_client() -> Saml2Client:
    """Return the one pysaml2 client for the whole process."""
    return get_saml_settings().get_client()