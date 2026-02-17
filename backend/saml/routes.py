from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, Response, JSONResponse
import logging
import base64
from lxml import etree

from saml2.client import Saml2Client
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT

from .settings import get_saml_client
from .auth import SAMLUser, create_session_response, create_logout_response, verify_session_token

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# SAML 2.0 XML namespaces
# ---------------------------------------------------------------------------
SAML_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml":  "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds":    "http://www.w3.org/2000/09/xmldsig#",
}


# ---------------------------------------------------------------------------
# Direct XML parser – used when pysaml2 cannot populate .assertion
# ---------------------------------------------------------------------------
def parse_saml_xml(xml_string: str) -> dict:
    """
    Parse raw SAML Response XML with lxml.
    Returns  { "name_id": str, "session_index": str, "attributes": {name: [values]} }
    """
    root = etree.fromstring(xml_string.encode("utf-8"))

    name_id_el = root.find(".//saml:Assertion/saml:Subject/saml:NameID", SAML_NS)
    name_id    = name_id_el.text if name_id_el is not None else None

    session_index_el = root.find(".//saml:Assertion", SAML_NS)
    session_index = session_index_el.get("SessionIndex") if session_index_el is not None else None
    if not session_index:
        # Some IdPs put it in AuthStatement
        auth_stmt = root.find(".//saml:Assertion/saml:AuthnStatement", SAML_NS)
        session_index = auth_stmt.get("SessionIndex") if auth_stmt is not None else None

    attributes: dict[str, list[str]] = {}
    for attr in root.findall(
        ".//saml:Assertion/saml:AttributeStatement/saml:Attribute", SAML_NS
    ):
        attr_name   = attr.get("Name", "")
        attr_values = [
            v.text for v in attr.findall("saml:AttributeValue", SAML_NS) if v.text
        ]
        attributes[attr_name] = attr_values

    return {"name_id": name_id, "session_index": session_index, "attributes": attributes}


# ---------------------------------------------------------------------------
# Normalise ADFS claim URIs → friendly keys
# ---------------------------------------------------------------------------
def normalise_attributes(name_id: str, attributes: dict) -> dict:
    """Extract email / display_name from raw ADFS attribute URIs."""
    email = (
        attributes.get(
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            [None],
        )[0]
        or attributes.get("mail", [None])[0]
        or (name_id if "@" in name_id else None)
    )

    display_name = (
        attributes.get(
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name", [None]
        )[0]
        or attributes.get("displayName", [None])[0]
        or email
    )

    return {"email": email, "display_name": display_name}


# ===========================================================================
# Routes
# ===========================================================================


@router.get("/login")
async def saml_login(next: str = "/"):
    """Initiates SAML login (SP → IdP)."""
    try:
        client: Saml2Client = get_saml_client()
        session_id, info = client.prepare_for_authenticate(
            relay_state=next,
            binding=BINDING_HTTP_REDIRECT,
        )
        headers     = dict(info["headers"])
        redirect_url = headers.get("Location")

        if not redirect_url:
            raise HTTPException(status_code=500, detail="Failed to initiate SAML login")

        logger.info("Redirecting to IdP for authentication")
        return RedirectResponse(url=redirect_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error initiating SAML login")
        raise HTTPException(status_code=500, detail=f"SAML login error: {str(e)}")


@router.post("/acs")
async def saml_acs(request: Request):
    """
    Assertion Consumer Service – receives the SAML Response from ADFS,
    extracts the user, creates a JWT session cookie, and redirects.
    """
    try:
        # ---------- raw form data ----------
        form                = await request.form()
        saml_response_b64   = form.get("SAMLResponse")
        relay_state         = form.get("RelayState", "/")

        if not saml_response_b64:
            raise HTTPException(status_code=400, detail="Missing SAMLResponse")

        # ---------- decode once, reuse everywhere ----------
        saml_response_xml: str = base64.b64decode(saml_response_b64).decode("utf-8")
        logger.debug(f"SAML Response preview: {saml_response_xml[:500]}")

        client = get_saml_client()

        # ==================================================================
        # Attempt 1 – let pysaml2 do everything (base64 string input)
        # ==================================================================
        name_id    = None
        session_index = None
        attributes = {}

        try:
            logger.debug("Attempt 1: pysaml2 full parse (base64 string)")
            authn_response = client.parse_authn_request_response(
                saml_response_b64,
                binding=BINDING_HTTP_POST,
            )
            name_id    = authn_response.assertion.subject.name_id.text
            if authn_response.assertion.authn_statement:
                session_index = authn_response.assertion.authn_statement[0].session_index
            attributes = authn_response.ava or {}
            logger.info("✓ Attempt 1 succeeded (pysaml2 full parse)")

        except Exception as e1:
            logger.warning(f"Attempt 1 failed: {type(e1).__name__}: {str(e1)[:200]}")

            # ==============================================================
            # Attempt 2 – pysaml2 loads() + verify()
            # ==============================================================
            try:
                logger.debug("Attempt 2: pysaml2 loads + verify")
                from saml2.response import AuthnResponse as _AuthnResponse

                resp = _AuthnResponse(
                    client.sec,
                    client.config.attribute_converters,
                    client.config.entityid,
                    return_addrs=[
                        client.config.endpoint(
                            "assertion_consumer_service", binding=BINDING_HTTP_POST
                        )
                    ],
                    outstanding_queries={},
                    allow_unsolicited=True,
                    want_assertions_signed=False,
                )
                resp.loads(saml_response_xml, decode=False)
                resp.verify()                          # populates .assertion

                name_id    = resp.assertion.subject.name_id.text
                if resp.assertion.authn_statement:
                    session_index = resp.assertion.authn_statement[0].session_index
                attributes = resp.ava or {}
                logger.info("✓ Attempt 2 succeeded (pysaml2 loads+verify)")

            except Exception as e2:
                logger.warning(f"Attempt 2 failed: {type(e2).__name__}: {str(e2)[:200]}")

                # ==========================================================
                # Attempt 3 – direct lxml parse (no pysaml2 at all)
                # ==========================================================
                try:
                    logger.debug("Attempt 3: direct lxml XML parse")
                    parsed     = parse_saml_xml(saml_response_xml)
                    name_id    = parsed["name_id"]
                    session_index = parsed.get("session_index")
                    attributes = parsed["attributes"]
                    logger.info("✓ Attempt 3 succeeded (direct lxml parse)")

                except Exception as e3:
                    logger.exception("Attempt 3 (lxml) also failed")
                    raise HTTPException(
                        status_code=401,
                        detail=f"All parsing attempts failed. Last error: {str(e3)}",
                    )

        # ==================================================================
        # Validate + build user + issue session cookie
        # ==================================================================
        if not name_id:
            logger.error("No NameID extracted from SAML response")
            raise HTTPException(status_code=401, detail="No user identifier in SAML response")

        friendly = normalise_attributes(name_id, attributes)

        logger.info(
            f"✓ SAML login successful  | user={name_id}  email={friendly['email']}"
        )

        user = SAMLUser(
            user_id=name_id,
            email=friendly["email"],
            display_name=friendly["display_name"],
            session_index=session_index,
            attributes=attributes,
        )

        return create_session_response(user, redirect_url=relay_state)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in SAML ACS")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/metadata")
async def saml_metadata():
    """Returns SP metadata XML for IdP registration."""
    try:
        client  = get_saml_client()
        acs_url = client.config.getattr("endpoints", "sp")[
            "assertion_consumer_service"
        ][0][0]
        entity  = client.config.entityid

        metadata_xml = (
            '<?xml version="1.0"?>\n'
            f'<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity}">\n'
            '  <SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="false"\n'
            '                   protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">\n'
            f'    <AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"\n'
            f'                             Location="{acs_url}" index="0" isDefault="true"/>\n'
            '  </SPSSODescriptor>\n'
            '</EntityDescriptor>'
        )

        return Response(content=metadata_xml, media_type="application/xml")

    except Exception as e:
        logger.exception("Failed to generate SP metadata")
        raise HTTPException(status_code=500, detail=f"Failed to generate metadata: {str(e)}")


@router.api_route("/logout", methods=["GET", "POST"])
async def saml_logout(request: Request, next: str = "/"):
    """
    Local logout: clears session cookie and redirects to IdP SLO.
    """
    logger.info(f"SAML logout requested | next={next}")

    try:
        from .settings import get_saml_settings
        settings = get_saml_settings()
        
        # 1. Clear session index if possible
        session_cookie = request.cookies.get(settings.session_cookie_name)
        if session_cookie:
            user = verify_session_token(session_cookie)
            if user and user.session_index:
                from .auth import revoke_session
                revoke_session(user.session_index)

        # 2. Redirect to IDP Logout (Shotgun approach for cookies)
        logout_url = settings.idp_slo_url
        logger.info(f"Redirecting to ADFS for Logout: {logout_url}")
        
        from .auth import create_logout_response
        return create_logout_response(redirect_url=logout_url)

    except Exception as e:
        logger.exception("Error during logout")
        return create_logout_response(redirect_url="/")


@router.get("/check")
async def saml_check(request: Request):
    """
    Check if user is authenticated via SAML session (JWT cookie).
    """
    from .settings import get_saml_settings
    settings = get_saml_settings()
    session_cookie = request.cookies.get(settings.session_cookie_name)

    if not session_cookie:
        raise HTTPException(status_code=401, detail="No active SAML session")

    user = verify_session_token(session_cookie)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired SAML session")

    return JSONResponse(
        status_code=200,
        content={
            "authenticated": True,
            "user": {
                "user_id": user.user_id,
                "email": user.email,
                "display_name": user.display_name,
                "attributes": user.attributes,
            },
        },
    )


@router.get("/slo")
async def saml_slo_response(request: Request):
    """
    Handles LogoutResponse from IdP (or final return).
    """
    relay_state = request.query_params.get("RelayState", "/")
    logger.info(f"SLO callback reached, returning to {relay_state}")
    return create_logout_response(redirect_url=relay_state)
