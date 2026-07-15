#!/usr/bin/env python3
"""Quick start script to verify the setup."""

import sys
from pathlib import Path

# Add the backend directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from automail.models import Email
from automail.pipeline.response.prompt_factory import create_response_system_prompt


def main():
    print("=" * 80)
    print("Mantly - Quick Setup Verification")
    print("=" * 80)

    # Test 1: System Prompt
    print("\n✓ Testing system prompt generation...")
    system_prompt = create_response_system_prompt()
    print(f"  System prompt length: {len(system_prompt)} characters")
    print(f"  Response prompt template detected: {'Draft an appropriate email response' in system_prompt}")

    # Test 2: Email Model
    print("\n✓ Testing Email model...")
    test_email = Email(
        id="test-setup",
        subject="Test Email",
        from_address="test@example.com",
        body="This is a test email body.",
        attachments=[],
    )
    print("  Email model created successfully")
    print(f"  Subject: {test_email.subject}")

    print("\n" + "=" * 80)
    print("Setup verification complete!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Start the server: uv run python -m automail.main")
    print("2. Visit API docs: http://localhost:8000/docs")
    print("3. Test the API: uv run python tests/test_api.py")
    print("=" * 80)


if __name__ == "__main__":
    main()
