import re
import sys
from pathlib import Path


def update_version():
    changelog_path = Path("CHANGELOG.md")
    readme_path = Path("README.md")

    if not changelog_path.exists() or not readme_path.exists():
        return

    # Extract latest version from Changelog: ## [1.1.4]
    changelog_content = changelog_path.read_text()
    version_match = re.search(r'##\s*\[(\d+\.\d+\.\d+)\]', changelog_content)

    if not version_match:
        return

    new_version = version_match.group(1)

    # Find version in README badge: version-1.1.4-blue
    readme_content = readme_path.read_text()
    badge_regex = r'(version-)(\d+\.\d+\.\d+)(-blue)'
    badge_match = re.search(badge_regex, readme_content)

    if badge_match:
        old_version = badge_match.group(2)

        # Only update if the version has actually changed
        if new_version != old_version:
            new_content = re.sub(badge_regex, f'version-{new_version}-blue', readme_content)
            readme_path.write_text(new_content)
            print(f"Updated README version badge from {old_version} to {new_version}")
            sys.exit(1)  # Exit with 1 to ensure the change is noticed/staged


if __name__ == "__main__":
    update_version()
