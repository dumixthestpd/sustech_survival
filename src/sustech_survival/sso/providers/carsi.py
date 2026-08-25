# =============================================================================
# CARSI DS WAYF — China CERNET Federation Discovery Service
# =============================================================================
# The CARSI WAYF page (ds.carsi.edu.cn) is an intermediary step when
# authenticating to services that support CARSI (Chinese academic ID federation).
#
# Flow for off-campus access to WoS/RSC/IEEE:
#   1. Service → institution combobox → "CHINA CERNET Federation"
#   2. Service → redirect to ds.carsi.edu.cn WAYF
#   3. User searches for their university → clicks it → form submits
#   4. CARSI → redirect to university's Shibboleth IdP (e.g. SUSTech CAS)
#   5. CAS login → consent → SAMLResponse → service ACS
#
# CARSI DS WAYF quirks:
#   - Search input: placeholder="请输入高校/机构名称" (search by Chinese name)
#   - Institution links are <li> elements with onclick="selectidp(entityID, name)"
#   - selectidp() sets hidden fields: $('#hid-inp').val(entityID), $('#show').val(name)
#   - Then user clicks the "登录" button to submit
#   - SUSTech's entityID: https://idp.sustech.edu.cn/idp/shibboleth
# =============================================================================

import re
from typing import Optional


# CARSI DS WAYF base URL
CARSI_DS_URL = "https://ds.carsi.edu.cn/login/index.html"

# SUSTech entityID within CARSI
SUSTECH_ENTITYID = "https://idp.sustech.edu.cn/idp/shibboleth"
SUSTECH_NAME = "南方科技大学（Southern University of Science and Technology）"


def login_via_carsi(
    page,
    *,
    target_entity_id: str,
    target_return_url: str,
    idp_entity_id: str = SUSTECH_ENTITYID,
    idp_display_name: str = SUSTECH_NAME,
    search_placeholder: str = "请输入高校/机构名称",
    submit_button_text: str = "登录",
    timeout: int = 30000,
) -> bool:
    """
    Handle the CARSI DS WAYF page.

    Args:
        page: Playwright page, already navigated to the CARSI WAYF URL.
        target_entity_id: The entityID query param passed to CARSI DS (service provider).
        target_return_url: The return URL query param passed to CARSI DS.
        idp_entity_id: The IdP entityID to select (default: SUSTech).
        idp_display_name: The display name of the IdP (for selectidp call).
        search_placeholder: Placeholder text of the search input.
        submit_button_text: Text on the submit button (default Chinese "登录").
        timeout: Max seconds to wait for redirects.

    Returns:
        True if redirect to IdP was initiated, False on failure.
    """
    import time

    page.wait_for_timeout(2000)

    # -- Step 1: Search for university --------------------------------------
    try:
        search_input = page.locator(
            f"input[placeholder='{search_placeholder}']"
        ).first
        search_input.wait_for(timeout=5000)
        search_input.fill(idp_display_name[:6])  # partial match is enough
        page.wait_for_timeout(1500)
        print(f"  → Searched for: {idp_display_name}")
    except Exception as e:
        print(f"  ⚠ Could not fill search input: {e}")
        return False

    # -- Step 2: Find and click the institution link -------------------------
    # The CARSI WAYF uses selectidp(entityID, name) onclick on <li> elements.
    # After search, only matching results remain visible.
    clicked = False
    for li in page.locator("li").all():
        try:
            txt = li.inner_text()
            if "Southern University of Science" in txt or "南方科技" in txt:
                li.click()
                clicked = True
                print(f"  → Clicked institution: {txt[:50]}")
                break
        except Exception:
            pass

    if not clicked:
        # Fallback: call selectidp directly
        print(f"  → Calling selectidp('{idp_entity_id}', '{idp_display_name}')")
        page.evaluate(
            f"selectidp('{idp_entity_id}', '{idp_display_name}')"
        )
        clicked = True

    page.wait_for_timeout(1000)

    # -- Step 3: Submit the form (click "登录") -----------------------------
    try:
        submit_btn = page.get_by_text(submit_button_text, exact=True).first
        submit_btn.click()
        print(f"  → Clicked submit: {submit_button_text}")
    except Exception as e:
        print(f"  ⚠ Could not click submit button: {e}")
        return False

    # -- Step 4: Wait for redirect to IdP -----------------------------------
    time.sleep(timeout / 1000)
    return True


def carsi_wayf_url(
    sp_entity_id: str,
    return_url: str,
    federation: str = "CHINA CERNET Federation",
) -> str:
    """
    Build the CARSI DS WAYF URL for a given SP.

    Args:
        sp_entity_id: The SP's entityID (e.g. for WoS: https://sp.tshhosting.com/shibboleth)
        return_url: The URL to return to after IdP auth.
        federation: The federation name (default: CHINA CERNET Federation).

    Returns:
        Full CARSI DS WAYF URL with query params.
    """
    import urllib.parse

    params = {
        "entityID": sp_entity_id,
        "return": return_url,
    }
    return f"{CARSI_DS_URL}?{urllib.parse.urlencode(params)}"
