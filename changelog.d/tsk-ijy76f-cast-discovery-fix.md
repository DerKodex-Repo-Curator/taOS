# Changelog Fragment

## Fixed

- Fixed paired device persistence when devices stop advertising. Paired devices now remain in the device list marked as offline when they stop advertising (e.g., when a TV is asleep).
- Fixed service browser creation to properly reuse the existing AsyncZeroconf instance from MdnsPublisher, preventing conflicts with mDNS publication.
- Fixed devices added by address to remain marked as online (they are considered manually added devices that should always be available).
- Added cast discovery routes to the application router, enabling access to `/api/cast/devices` and related endpoints.