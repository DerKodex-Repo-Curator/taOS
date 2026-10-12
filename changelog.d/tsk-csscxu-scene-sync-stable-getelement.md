### Fixed
- SceneSync is no longer disposed and recreated on every canvas update when `getElement` changes, preventing silent loss of pending local edits (shape drags, text changes). The sync now lives for the lifetime of `(projectId, elementId, readOnly)` and receives a stable `getElement` that always forwards to the latest element map.
- Flush pending SceneSync writes before dispose to prevent edits from being dropped when closing the board or switching project within the debounce window.
- Add `captureUpdate: CaptureUpdateAction.NEVER` to `api.updateScene` calls to keep remote scenes out of undo.
- Fix `viewModeEnabled` logic to correctly enable editing when `readOnly=false` and no `projectId` is present.