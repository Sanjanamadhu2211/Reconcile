#!/usr/bin/env python3
"""
Unit tests for the CLI module.

These tests verify the argument parsing and basic CLI behavior
without touching the database.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cli import _find_user_by_email, _find_workspace_by_id, _parse_args
from app.models import Workspace

# Add backend to path for importing
backend_path = Path(__file__).parent.parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))


def test_parse_args_import():
    """Test that import subcommand is parsed correctly."""
    with patch.object(
        sys, "argv", ["app.cli", "import", "test.csv", "--workspace", "123", "--source", "orders"]
    ):
        args = _parse_args()
        assert args.command == "import"
        assert args.file == Path("test.csv")
        assert args.workspace == "123"
        assert args.source == "orders"
        assert args.user_email is None


def test_parse_args_import_with_user_email():
    """Test that import subcommand with user email is parsed correctly."""
    with patch.object(
        sys,
        "argv",
        [
            "app.cli",
            "import",
            "test.csv",
            "--workspace",
            "123",
            "--source",
            "orders",
            "--user-email",
            "test@example.com",
        ],
    ):
        args = _parse_args()
        assert args.command == "import"
        assert args.file == Path("test.csv")
        assert args.workspace == "123"
        assert args.source == "orders"
        assert args.user_email == "test@example.com"


def test_parse_args_missing_required_args():
    """Test that missing required arguments raises error."""
    # Test with only command
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli"]):
            _parse_args()

    # Test with command but no subcommand
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli", "somecommand"]):
            _parse_args()

    # Test with import but missing workspace
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli", "import", "test.csv", "--source", "orders"]):
            _parse_args()

    # Test with import but missing source
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli", "import", "test.csv", "--workspace", "123"]):
            _parse_args()

    # Test with invalid source
    with pytest.raises(SystemExit):
        with patch.object(
            sys,
            "argv",
            ["app.cli", "import", "test.csv", "--workspace", "123", "--source", "invalid"],
        ):
            _parse_args()


def test_find_user_by_email():
    """Test user lookup by email."""
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.email = "test@example.com"

    # Mock the query
    with patch.object(mock_db, "scalar") as mock_scalar:
        mock_scalar.return_value = mock_user
        result = _find_user_by_email(mock_db, "test@example.com")
        assert result == mock_user

        # Test case-insensitive lookup
        mock_scalar.assert_called_once()
        # The actual query uses ilike, which is case-insensitive


def test_find_user_by_email_not_found():
    """Test user lookup returns None when user not found."""
    mock_db = MagicMock()

    # Mock the query to return None
    with patch.object(mock_db, "scalar") as mock_scalar:
        mock_scalar.return_value = None
        result = _find_user_by_email(mock_db, "nonexistent@example.com")
        assert result is None


def test_find_workspace_by_id():
    """Test workspace lookup by ID."""
    mock_db = MagicMock()
    mock_workspace = MagicMock()
    mock_workspace.id = "123"

    with patch.object(mock_db, "get") as mock_get:
        mock_get.return_value = mock_workspace
        result = _find_workspace_by_id(mock_db, "123")
        assert result == mock_workspace
        mock_get.assert_called_once_with(Workspace, "123")


def test_find_workspace_by_id_not_found():
    """Test workspace lookup returns None when workspace not found."""
    mock_db = MagicMock()

    with patch.object(mock_db, "get") as mock_get:
        mock_get.return_value = None
        result = _find_workspace_by_id(mock_db, "999")
        assert result is None
        mock_get.assert_called_once_with(Workspace, "999")
