import os
import re
import shutil

MAPPING = {
    "admin_routes": "routers",
    "admin_config_routes": "routers",
    "auth_routes": "routers",
    "bootstrap_admin": "routers",
    "bootstrap_routes": "routers",
    "distributor_routes": "routers",
    "page_routes": "routers",
    "roster_routes": "routers",
    "student_routes": "routers",
    "treasurer_routes": "routers",
    "volunteer_routes": "routers",
    "database": "db",
    "schema_v2": "db",
    "config": "core",
    "security": "core",
    "auth": "core",
    "session_auth": "core",
    "settings_manager": "core",
    "mailer": "services",
    "audit": "services",
    "seed": "scripts",
    "seed_online_sales": "scripts"
}

def main():
    # Create dirs
    for folder in set(MAPPING.values()):
        os.makedirs(folder, exist_ok=True)
        init_file = os.path.join(folder, '__init__.py')
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write('')

    # Move files
    for mod, folder in MAPPING.items():
        src = f"{mod}.py"
        if os.path.exists(src):
            dst = os.path.join(folder, src)
            print(f"Moving {src} to {dst}")
            shutil.move(src, dst)
        else:
            print(f"Warning: {src} not found in root.")

    # Now iterate all python files in the repo and fix imports
    def fix_imports_in_file(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        new_lines = []
        changed = False
        
        for line in lines:
            # Match "from X import Y" or "from X.Y import Z"
            # But we only want to match top-level modules we moved, e.g. "from schema_v2"
            m1 = re.match(r"^(\s*)from\s+([a-zA-Z0-9_]+)\s+import\s+(.*)", line)
            if m1:
                indent, mod, rest = m1.groups()
                if mod in MAPPING:
                    folder = MAPPING[mod]
                    line = f"{indent}from {folder}.{mod} import {rest}"
                    changed = True

            # Match "import X"
            m2 = re.match(r"^(\s*)import\s+([a-zA-Z0-9_]+)\s*$", line)
            if m2:
                indent, mod = m2.groups()
                if mod in MAPPING:
                    folder = MAPPING[mod]
                    line = f"{indent}from {folder} import {mod}"
                    changed = True
                    
            new_lines.append(line)
            
        if changed:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_lines))
            print(f"Updated imports in {filepath}")

    # Collect all .py files
    py_files = []
    for root, dirs, files in os.walk('.'):
        if any(skip in root for skip in ['.venv', '.git', '__pycache__']):
            continue
        for file in files:
            if file.endswith('.py') and file != 'refactor_repo.py':
                py_files.append(os.path.join(root, file))

    for pyf in py_files:
        fix_imports_in_file(pyf)

    print("Refactor complete.")

if __name__ == "__main__":
    main()
