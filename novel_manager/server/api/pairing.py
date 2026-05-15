from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services.pairing_service import (
    create_pairing_session,
    confirm_pairing,
    list_paired_devices,
    revoke_device,
)

router = APIRouter(tags=["pairing"])


class ConfirmPairingRequest(BaseModel):
    pairing_code: str
    device_id: str
    device_name: str | None = None


class RevokeRequest(BaseModel):
    device_id: str


@router.post("/api/pairing/create")
def pairing_create(request: Request):
    """Create a new pairing code.

    Returns a pairing code that can be used on a mobile device to authorize access.
    The code expires in 5 minutes and can only be used once.
    """
    result = create_pairing_session(request.app.state.repo_path)

    # Build pair_url if we have the request info
    host = request.headers.get("host", "localhost:8765")
    scheme = request.url.scheme
    result["pair_url"] = f"{scheme}://{host}/#pair={result['pairing_code']}"

    return result


@router.post("/api/pairing/confirm")
def pairing_confirm(request: Request, body: ConfirmPairingRequest):
    """Confirm pairing with a code.

    Mobile devices call this with the pairing code to get an access token.
    The token is returned in plain text only once - it must be saved securely.
    """
    user_agent = request.headers.get("user-agent", "")
    return confirm_pairing(
        request.app.state.repo_path,
        body.pairing_code,
        body.device_id,
        body.device_name,
        user_agent,
    )


@router.get("/api/pairing/devices")
def pairing_devices(request: Request):
    """List all paired devices.

    Returns a list of all devices that have been authorized to access this repository.
    """
    devices = list_paired_devices(request.app.state.repo_path)
    return {"ok": True, "devices": devices}


@router.post("/api/pairing/devices/{device_id}/revoke")
def pairing_revoke(request: Request, device_id: str):
    """Revoke a device's authorization.

    Once revoked, the device will no longer be able to access the repository.
    """
    return revoke_device(request.app.state.repo_path, device_id)
