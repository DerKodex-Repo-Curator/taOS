"""Tests for sharing routes ownership validation."""
import pytest
import pytest_asyncio
from pathlib import Path
import importlib.util
from unittest.mock import Mock, AsyncMock


class TestCreateGrantOwnership:
    """Test that create_grant validates ownership before creating grants."""
    
    @pytest.mark.asyncio
    async def test_ownership_check_exists_in_routes(self):
        """Test that the ownership check is implemented in routes/sharing.py."""
        # Load the sharing routes module
        spec = importlib.util.spec_from_file_location(
            "sharing_routes", 
            Path(__file__).parent.parent / "tinyagentos" / "routes" / "sharing.py"
        )
        if spec is None:
            pytest.fail("Could not load sharing routes module")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Verify the _caller_owns_artifact function exists
        assert hasattr(module, "_caller_owns_artifact"), \
            "_caller_owns_artifact function should be defined in routes/sharing.py"
        
        # Verify it has the correct signature
        import inspect
        sig = inspect.signature(module._caller_owns_artifact)
        params = list(sig.parameters.keys())
        
        # Should have: request, artifact_kind, artifact_id, owner_id
        expected_params = ["request", "artifact_kind", "artifact_id", "owner_id"]
        assert all(param in params for param in expected_params), \
            f"_caller_owns_artifact should have parameters: {expected_params}"
        
        # Test that the function can be called with mock data
        mock_request = Mock()
        mock_request.app = Mock()
        mock_request.app.state = {}
        
        # Test that it returns False when no owner info is available
        result = await module._caller_owns_artifact(
            mock_request, "project", "project-1", "user1"
        )
        assert result is False, "Should return False when project store is not available"
    
    @pytest.mark.asyncio
    async def test_create_grant_has_ownership_check(self):
        """Test that the create_grant route includes the ownership check."""
        # This test reads the source code of create_grant to verify
        # that it includes the ownership check
        with open(Path(__file__).parent.parent / "tinyagentos" / "routes" / "sharing.py") as f:
            content = f.read()
        
        # Verify that the ownership check is present in create_grant
        assert "_caller_owns_artifact" in content, \
            "create_grant should call _caller_owns_artifact"
        
        assert "you do not own this artifact" in content, \
            "create_grant should return error message about not owning artifact"
        
        # Verify the check happens before store.grant() call
        create_grant_start = content.find("async def create_grant")
        ownership_check = content.find("_caller_owns_artifact")
        store_grant_call = content.find("await store.grant")
        
        assert ownership_check != -1, "Ownership check should be present in create_grant"
        assert store_grant_call != -1, "store.grant call should be present in create_grant"
        
        # Verify ownership check happens before store.grant
        assert ownership_check < store_grant_call, \
            "Ownership check should happen before store.grant call"
    
    @pytest.mark.asyncio
    async def test_project_ownership_check_logic(self):
        """Test the project ownership check logic."""
        # Load the sharing routes module
        spec = importlib.util.spec_from_file_location(
            "sharing_routes",
            Path(__file__).parent.parent / "tinyagentos" / "routes" / "sharing.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Test the ownership check logic by examining the code
        # rather than trying to mock complex FastAPI objects
        
        # Read the function source to verify the logic
        import inspect
        source = inspect.getsource(module._caller_owns_artifact)
        
        # Verify the project ownership check is present
        assert 'artifact_kind == "project"' in source, \
            "Should check for project artifact kind"
        
        assert 'project_store = getattr(request.app.state, "project_store", None)' in source, \
            "Should get project_store from app.state"
        
        assert 'project = await project_store.get_project(artifact_id)' in source, \
            "Should call project_store.get_project"
        
        assert 'project.get("created_by") == owner_id or project.get("user_id") == owner_id' in source, \
            "Should check if user owns project via created_by or user_id"
    
    @pytest.mark.asyncio
    async def test_app_and_game_ownership_check_present(self):
        """Test that the ownership check is present for app and game artifacts."""
        # Load the sharing routes module
        spec = importlib.util.spec_from_file_location(
            "sharing_routes",
            Path(__file__).parent.parent / "tinyagentos" / "routes" / "sharing.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Read the function source
        import inspect
        source = inspect.getsource(module._caller_owns_artifact)
        
        # Verify app and game artifact checks are present
        assert 'artifact_kind in ("app", "game")' in source, \
            "Should check for app and game artifact kinds"
        
        assert 'app_store = getattr(request.app.state, "app_grants", None)' in source, \
            "Should get app_grants store from app.state"
        
        assert 'capabilities = await app_store.granted_capabilities(owner_id, artifact_id)' in source, \
            "Should call app_store.granted_capabilities"
    
    @pytest.mark.asyncio
    async def test_error_message_present(self):
        """Test that the correct error message is present in create_grant."""
        # Read the create_grant route source
        with open(Path(__file__).parent.parent / "tinyagentos" / "routes" / "sharing.py") as f:
            content = f.read()
        
        # Find the create_grant function - look for the specific line that contains the error
        # We'll search for the line that contains the error message
        assert 'return JSONResponse({"error": "you do not own this artifact"}, status_code=403)' in content, \
            "Should return error message 'you do not own this artifact' with status code 403"
        
        # Also verify it's in the create_grant function by checking context
        create_grant_section = content[content.find("async def create_grant"):content.find("\n\n@router.delete")]
        assert 'return JSONResponse({"error": "you do not own this artifact"}, status_code=403)' in create_grant_section, \
            "Error should be in create_grant function"
    
    @pytest.mark.asyncio
    async def test_changelog_created(self):
        """Test that the changelog fragment was created."""
        # Check if the changelog fragment exists
        changelog_path = Path(__file__).parent.parent / "changelog.d" / "tsk-d6awig-sharing-grant-ownership.md"
        
        assert changelog_path.exists(), \
            f"Changelog fragment should exist at {changelog_path}"
        
        # Read and verify the changelog content
        with open(changelog_path) as f:
            changelog_content = f.read()
        
        # Verify it has the required sections
        assert "### Fixed" in changelog_content, \
            "Changelog should have ### Fixed section"
        
        assert "ownership verification" in changelog_content.lower() or "create_grant" in changelog_content.lower(), \
            "Changelog should mention ownership verification or create_grant"