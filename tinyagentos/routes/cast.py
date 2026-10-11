"""Routes for cast (Chromecast/AirPlay) device management."""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from tinyagentos.services.cast_discovery import CastDiscovery
from tinyagentos.services.mdns_publisher import MdnsPublisher

# Create the router
router = APIRouter()

# Cast discovery dependency function
def get_cast_discovery(request: Request) -> CastDiscovery:
    """Get cast discovery from app state."""
    return getattr(request.app.state, 'cast_discovery', None)

# Cast route handlers
@router.get("/api/cast/devices")
async def get_cast_devices(request: Request) -> JSONResponse:
    """List all cast devices (discovered + paired) for the current user."""
    cast_discovery = get_cast_discovery(request)
    if not cast_discovery:
        return JSONResponse({"devices": []})
    
    devices = cast_discovery.get_all_devices()
    return JSONResponse({"devices": devices})

@router.post("/api/cast/devices/{device_id}/pair")
async def pair_cast_device(request: Request, device_id: str) -> JSONResponse:
    """Pair with a cast device."""
    body = await request.json() if request.body() else {}
    
    friendly_name = body.get("friendly_name", "")
    kind = body.get("kind", "")
    address = body.get("address", "")
    port = body.get("port", 0)
    
    cast_discovery = get_cast_discovery(request)
    if not cast_discovery:
        return JSONResponse({"error": "cast discovery not available"}, status_code=500)
    
    cast_discovery.pair_device(device_id, friendly_name, kind, address, port)
    return JSONResponse({"status": "paired", "device_id": device_id})

@router.delete("/api/cast/devices/{device_id}/unpair")
async def unpair_cast_device(request: Request, device_id: str) -> JSONResponse:
    """Remove a device from the paired registry."""
    cast_discovery = get_cast_discovery(request)
    if not cast_discovery:
        return JSONResponse({"error": "cast discovery not available"}, status_code=500)
    
    cast_discovery.unpair_device(device_id)
    return JSONResponse({"status": "unpaired", "device_id": device_id})

@router.post("/api/cast/devices")
async def add_cast_device(request: Request) -> JSONResponse:
    """Manually add a cast device by its static address."""
    body = await request.json() if request.body() else {}
    
    device_id = body.get("device_id", "")
    friendly_name = body.get("friendly_name", "")
    kind = body.get("kind", "")
    address = body.get("address", "")
    port = body.get("port", 0)
    
    if not device_id or not address:
        raise HTTPException(status_code=400, detail="device_id and address are required")
    
    cast_discovery = get_cast_discovery(request)
    if not cast_discovery:
        return JSONResponse({"error": "cast discovery not available"}, status_code=500)
    
    cast_discovery.add_device_by_address(device_id, friendly_name, kind, address, port)
    return JSONResponse({"status": "added", "device_id": device_id})
