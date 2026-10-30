#!/usr/bin/env python3
"""Unit tests for the CLI module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cli import _find_user, _find_workspace, _parse_args
from app.models import Workspace


def test_parse_args_import():
    with patch.object(
        sys, "argv", ["app.cli", "import", "test.csv", "--workspace", "123", "--source", "orders"]
    ):
        args = _parse_args(None)
        assert args.command == "import"
        assert args.file == Path("test.csv")
        assert args.workspace == "123"
        assert args.source == "orders"
        assert args.user_email is None


def test_parse_args_import_with_user_email():
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
        args = _parse_args(None)
        assert args.command == "import"
        assert args.file == Path("test.csv")
        assert args.workspace == "123"
        assert args.source == "orders"
        assert args.user_email == "test@example.com"


def test_parse_args_missing_required_args():
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli"]):
            _parse_args(None)

    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli", "somecommand"]):
            _parse_args(None)

    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli", "import", "test.csv", "--source", "orders"]):
            _parse_args(None)

    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["app.cli", "import", "test.csv", "--workspace", "123"]):
            _parse_args(None)

    with pytest.raises(SystemExit):
        with patch.object(
            sys,
            "argv",
            ["app.cli", "import", "test.csv", "--workspace", "123", "--source", "invalid"],
        ):
            _parse_args(None)


def test_find_user():
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.email = "test@example.com"

    with patch.object(mock_db, "scalar") as mock_scalar:
        mock_scalar.return_value = mock_user
        result = _find_user(mock_db, "test@example.com")
        assert result == mock_user
        mock_scalar.assert_called_once()


def test_find_user_not_found():
    mock_db = MagicMock()

    with patch.object(mock_db, "scalar") as mock_scalar:
        mock_scalar.return_value = None
        result = _find_user(mock_db, "nonexistent@example.com")
        assert result is None


def test_find_workspace():
    mock_db = MagicMock()
    mock_workspace = MagicMock()
    mock_workspace.id = "123"

    with patch.object(mock_db, "get") as mock_get:
        mock_get.return_value = mock_workspace
        result = _find_workspace(mock_db, "123")
        assert result == mock_workspace
        mock_get.assert_called_once_with(Workspace, "123")


def test_find_workspace_not_found():
    mock_db = MagicMock()

    with patch.object(mock_db, "get") as mock_get:
        mock_get.return_value = None
        result = _find_workspace(mock_db, "999")
        assert result is None
        mock_get.assert_called_once_with(Workspace, "999")
