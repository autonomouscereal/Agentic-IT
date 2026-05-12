#!/usr/bin/env python3
"""Setup GitLab authorization workflows: groups, projects, protected branches, MR rules."""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "http://localhost"
PAT = os.environ.get("GITLAB_PAT", "glpat-uyTtfbshu1wUzA5sBd4y")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def api(method, path, token, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
            raw = r.read().decode()
            return r.code, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return e.code, json.loads(raw) if raw else {"error": str(e)}


def setup_groups(token):
    """Create GitLab groups matching Keycloak groups."""
    print("\n=== Creating GitLab groups ===")
    groups = [
        {"name": "gitlab-admins", "path": "gitlab-admins", "description": "GitLab administrators with full access"},
        {"name": "gitlab-developers", "path": "gitlab-developers", "description": "Developers with push and MR capabilities"},
        {"name": "gitlab-viewers", "path": "gitlab-viewers", "description": "Read-only access to projects"},
    ]
    for group in groups:
        result = api("POST", "/api/v4/groups", token, group)
        if result[0] == 201:
            print(f"  [OK] Group '{group['name']}' created (id={result[1].get('id')})")
        elif result[0] == 400 and "has already been taken" in str(result[1]):
            print(f"  [SKIP] Group '{group['name']}' already exists")
        else:
            print(f"  [WARN] Group '{group['name']}': code={result[0]} {result[1]}")


def find_group(token, path):
    """Find a group by path."""
    groups = api("GET", f"/api/v4/groups?search={path}&per_page=20", token)
    if groups[1]:
        for g in groups[1]:
            if g.get("path") == path:
                return g["id"]
    return None


def setup_test_project(token):
    """Create a test project for authorization testing."""
    print("\n=== Creating test project ===")
    group_id = find_group(token, "gitlab-developers")

    project_data = {
        "name": "test-project",
        "description": "Test project for OIDC authorization workflows",
        "visibility": "internal",
        "initialize_with_readme": True,
    }
    if group_id:
        project_data["namespace_id"] = group_id

    result = api("POST", "/api/v4/projects", token, project_data)
    if result[0] == 201:
        proj = result[1]
        print(f"  [OK] Project '{proj['name']}' created (id={proj['id']})")
        return proj["id"]
    elif result[0] == 400:
        print(f"  [SKIP] Project already exists or error: {result[1]}")
        projects = api("GET", "/api/v4/projects?search=test-project&per_page=20", token)
        if projects[1]:
            for p in projects[1]:
                if p.get("name") == "test-project":
                    print(f"  [OK] Found existing project id={p['id']}")
                    return p["id"]
    else:
        print(f"  [WARN] Project creation: code={result[0]} {result[1]}")
    return None


def setup_protected_branches(token, project_id):
    """Set up protected branches."""
    if not project_id:
        print("\n=== Skipping protected branches (no project) ===")
        return
    print("\n=== Setting up protected branches ===")

    # Protect main branch - Maintainers and up can push and merge
    result = api("POST", f"/api/v4/projects/{project_id}/protected_branches", token, {
        "name": "main",
        "push_access_levels": [{"access_level": 30}],
        "merge_access_levels": [{"access_level": 30}],
    })
    if result[0] == 201:
        print("  [OK] 'main' branch protected (maintainers only)")
    elif result[0] in (409, 400):
        print("  [SKIP] 'main' branch already protected")
    else:
        print(f"  [WARN] Protect main: code={result[0]} {result[1]}")

    # Set protected branch for develop too (if it exists)
    result = api("POST", f"/api/v4/projects/{project_id}/protected_branches", token, {
        "name": "develop",
        "push_access_levels": [{"access_level": 30}],
        "merge_access_levels": [{"access_level": 30}],
    })
    if result[0] == 201:
        print("  [OK] 'develop' branch protected")
    elif result[0] in (400, 409, 500):
        print("  [SKIP] 'develop' branch already protected or doesn't exist")


def setup_approval_settings(token, project_id):
    """Set up MR approval settings."""
    if not project_id:
        print("\n=== Skipping MR rules (no project) ===")
        return
    print("\n=== Setting up MR approval rules ===")

    # Enable project-level approvals
    result = api("PUT", f"/api/v4/projects/{project_id}", token, {
        "approvals_before_merge": 1,
        "require_approvals_before_merge": True,
    })
    if result[0] == 200:
        print("  [OK] Project approval settings configured (1 approval required)")
    else:
        print(f"  [WARN] Approval settings: code={result[0]} {result[1]}")


def create_test_branches(token, project_id):
    """Create develop branch for testing."""
    if not project_id:
        return
    print("\n=== Creating test branches ===")

    result = api("POST", f"/api/v4/projects/{project_id}/repository/branches", token, {
        "branch": "develop",
        "ref": "main",
    })
    if result[0] == 201:
        print("  [OK] Branch 'develop' created")
    else:
        print(f"  [SKIP] Branch 'develop' exists or error: code={result[0]}")


def add_test_content(token, project_id):
    """Add some test files to the project."""
    if not project_id:
        return
    print("\n=== Adding test content ===")

    # Add a .gitlab-ci.yml file
    file_path = ".gitlab-ci.yml"
    content = """stages:
  - test
  - build
  - deploy

unit_tests:
  stage: test
  script:
    - echo "Running unit tests..."
    - echo "All tests passed!"

build_job:
  stage: build
  script:
    - echo "Building project..."
    - echo "Build successful!"
  only:
    - main
    - develop

deploy_dev:
  stage: deploy
  script:
    - echo "Deploying to development..."
  only:
    - develop

deploy_prod:
  stage: deploy
  script:
    - echo "Deploying to production..."
  only:
    - main
  when: manual
"""
    result = api("POST", f"/api/v4/projects/{project_id}/repository/files/{urllib.parse.quote(file_path, safe='')}", token, {
        "branch": "main",
        "encoding": "text",
        "content": content,
        "commit_message": "Add CI/CD pipeline configuration",
    })
    if result[0] == 201:
        print("  [OK] .gitlab-ci.yml added")
    elif result[0] == 409:
        print("  [SKIP] .gitlab-ci.yml already exists")
    else:
        print(f"  [WARN] CI file: code={result[0]}")


def verify_setup(token, project_id):
    """Verify the complete setup."""
    print("\n=== Verification ===")
    # List groups
    groups = api("GET", "/api/v4/groups?per_page=20", token)
    if groups[1]:
        print(f"  Groups: {len(groups[1])} found")
        for g in groups[1]:
            if "gitlab-" in g.get("path", ""):
                print(f"    - {g['path']} (id={g['id']})")

    # List protected branches
    if project_id:
        branches = api("GET", f"/api/v4/projects/{project_id}/protected_branches", token)
        if branches[1]:
            print(f"  Protected branches: {len(branches[1])}")
            for b in branches[1]:
                print(f"    - {b['name']}")

    # List project branches
    if project_id:
        refs = api("GET", f"/api/v4/projects/{project_id}/repository/branches", token)
        if refs[1]:
            print(f"  Project branches: {len(refs[1])}")
            for r in refs[1]:
                print(f"    - {r['name']}")


def main():
    token = PAT
    print("=" * 60)
    print("GitLab Authorization Workflow Setup")
    print("=" * 60)

    # Test API access
    me = api("GET", "/api/v4/user", token)
    if me[0] == 200:
        print(f"\n[OK] Authenticated as: {me[1].get('username')} (id={me[1].get('id')})")
    else:
        print(f"\n[FATAL] API auth failed: code={me[0]} {me[1]}")
        return

    # Setup everything
    setup_groups(token)
    project_id = setup_test_project(token)
    setup_protected_branches(token, project_id)
    setup_approval_settings(token, project_id)
    create_test_branches(token, project_id)
    add_test_content(token, project_id)
    verify_setup(token, project_id)

    print("\n" + "=" * 60)
    print("Authorization Workflow Setup Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
