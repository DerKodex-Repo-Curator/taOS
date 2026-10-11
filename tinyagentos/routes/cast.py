"""Routes for cast (Chromecast/AirPlay) device management."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tinyagentos.auth_context import CurrentUser, current_user

router = APIRouter()


class AddDeviceIn(BaseModel):
    device_id: str = Field(min_length=1)
    friendly_name: str = Field(default="", max_length=200)
    kind: str = Field(pattern="^(googlecast|airplay|raop)$")
    address: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


def _get_cast_discovery(request: Request):
    """Get cast discovery from app state."""
    discovery = getattr(request.app.state, "cast_discovery", None)
    if discovery is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "cast discovery unavailable"},
        )
    return discovery


@router.get("/api/cast/devices")
async def get_cast_devices(
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    """List all cast devices (discovered + paired) for the current user."""
    discovery = _get_cast_discovery(request)
    devices = await discovery.devices()
    return {"devices": devices}


@router.post("/api/cast/devices/{device_id}/pair")
async def pair_cast_device(
    device_id: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    """Pair with a cast device.

    The device must be either currently discovered or already paired.
    Body can optionally override friendly_name, kind, address, port.
    """
    discovery = _get_cast_discovery(request)

    # Check if device exists in discovered or paired
    devices = await discovery.devices()
    device = next((d for d in devices if d["id"] == device_id), None)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    # Parse optional body overrides
    body = {}
    try:
        body = await request.json()
    except json.JSONDecodeError:
        pass

    friendly_name = body.get("friendly_name", device["friendly_name"])
    kind = body.get("kind", device["kind"])
    address = body.get("address", device["address"])
    port = body.get("port", device["port"])

    await discovery.pair(device_id, friendly_name, kind, address, port)
    return {"status": "paired", "device_id": device_id}


@router.delete("/api/cast/devices/{device_id}")
async def unpair_cast_device(
    device_id: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    """Remove a device from the paired registry (NOT /unpair)."""
    discovery = _get_cast_discovery(request)

    # Check if device is paired
    devices = await discovery.devices()
    device = next((d for d in devices if d["id"] == device_id and d["paired"]), None)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found or not paired")

    await discovery.unpair(device_id)
    return {"status": "unpaired", "device_id": device_id}


@router.post("/api/cast/devices")
async def add_cast_device(
    body: AddDeviceIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    """Manually add a cast device by its static address.

    For hosts that can never do multicast discovery.
    """
    discovery = _get_cast_discovery(request)
    await discovery.add_by_address(
        device_id=body.device_id,
        friendly_name=body.friendly_name,
        kind=body.kind,
        address=body.address,
        port=body.port,
    )
    return JSONResponse(
        {"status": "added", "device_id": body.device_id},
        status_code=201,
    )