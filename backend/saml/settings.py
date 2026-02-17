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
        self.sp_slo_url = os.getenv(
            "SAML_SP_SLO_URL",
            "https://askme.ipr.res.in/saml/slo",
        )
        self.sp_cert_file = os.getenv(
            "SAML_SP_CERT_FILE",
            "/home/vkpatel/askme.crt", # Default from user's env
        )
        self.sp_key_file = os.getenv(
            "SAML_SP_KEY_FILE",
            "/home/vkpatel/askme.key", # Default from user's env
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
            "idp.crt",
        )
        self.idp_slo_url = os.getenv(
            "SAML_IDP_SLO_URL",
            "https://adfs.ipr.res.in/adfs/ls/?wa=wsignout1.0",
        )

        # ===== Session / JWT =====
        # In production set SESSION_SECRET to a long random string in .env
        # The fallback generates one per process-start (fine for dev, NOT for
        # multi-worker production – tokens won't survive a restart).
        self.session_secret: str = os.getenv(
            "SAML_SESSION_SECRET",          # Match .env
            os.getenv("SESSION_SECRET", secrets.token_hex(32))
        )
        self.session_max_age: int = int(
            os.getenv("SAML_SESSION_MAX_AGE", os.getenv("SESSION_MAX_AGE", "3600"))
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

    # ------------------------------------------------------------------
    # python3-saml (Onelogin) config
    # ------------------------------------------------------------------
    def _read_file_clean(self, path: str) -> str:
        """Helper to read and clean cert/key files for Onelogin."""
        if not path or not os.path.exists(path):
            return ""
        with open(path, "r") as f:
            content = f.read()
        return (
            content
            .replace("-----BEGIN CERTIFICATE-----", "")
            .replace("-----END CERTIFICATE-----", "")
            .replace("-----BEGIN PRIVATE KEY-----", "")
            .replace("-----END PRIVATE KEY-----", "")
            .replace("-----BEGIN RSA PRIVATE KEY-----", "")
            .replace("-----END RSA PRIVATE KEY-----", "")
            .replace("\n", "")
            .strip()
        )

    def to_onelogin_settings(self) -> dict:
        """
        Generate setting dict for python3-saml (OneLogin).
        Use this for OneLogin_Saml2_Auth initialization.
        """
        idp_cert = self._read_file_clean(self.idp_cert_file)
        sp_cert = self._read_file_clean(self.sp_cert_file)
        sp_key = self._read_file_clean(self.sp_key_file)

        return {
            "strict": True,
            "debug": True,
            "sp": {
                "entityId": self.sp_entity_id,
                "assertionConsumerService": {
                    "url": self.sp_acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
                "singleLogoutService": {
                    "url": self.sp_slo_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
                "x509cert": sp_cert,
                "privateKey": sp_key,
            },
            "idp": {
                "entityId": self.idp_entity_id,
                "singleSignOnService": {
                    "url": self.idp_sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "singleLogoutService": {
                    "url": self.idp_slo_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "x509cert": idp_cert,
            },
            "security": {
                "nameIdEncrypted": False,
                "authnRequestsSigned": True, # ADFS often wants this
                "logoutRequestSigned": True, # ADFS definitely wants this
                "logoutResponseSigned": False,
                "signMetadata": False,
                "wantMessagesSigned": False,
                "wantAssertionsSigned": False, # Adjust based on ADFS
                "wantNameId": True,
                "wantNameIdEncrypted": False,
                "wantAssertionsEncrypted": False,
                "allowUnsolicited": True, 
                "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
                "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
            }
        }


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