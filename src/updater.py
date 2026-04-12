import os
import sys
import platform
import aiohttp
import shutil
import stat
import zipfile
import asyncio
import subprocess


def toggle_autoupdate_env(new_state: bool):
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"AUTOUPDATE={str(new_state)}\n")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found = False
    with open(env_path, "w", encoding="utf-8") as f:
        for line in lines:
            if line.startswith("AUTOUPDATE="):
                f.write(f"AUTOUPDATE={str(new_state)}\n")
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f"AUTOUPDATE={str(new_state)}\n")


def cleanup_old_executables():
    """Silently cleans up leftover .old files from previous updates upon successful boot."""
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        old_path = f"{exe_path}.old"
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass


async def check_for_updates(github_repo, current_version):
    if getattr(sys, 'frozen', False):
        if not github_repo:
            return False
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/repos/{github_repo}/releases/latest"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    latest_tag = data.get("tag_name", "")
                    if latest_tag and latest_tag != current_version:
                        return True
    else:
        process = await asyncio.create_subprocess_shell(
            "git fetch && git status -sb",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        if b"behind" in stdout:
            return True
    return False


async def run_update(github_repo, log_callback=None):
    async def log(msg):
        if log_callback:
            await log_callback(msg)
        else:
            print(msg)

    if getattr(sys, 'frozen', False):
        if not github_repo:
            await log("Error: GITHUB_REPO not set in .env. Cannot download latest release.")
            return False

        system = platform.system().lower()
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/repos/{github_repo}/releases/latest"
            async with session.get(url) as resp:
                if resp.status != 200:
                    await log("Failed to find latest release on GitHub.")
                    return False

                data = await resp.json()
                assets = data.get("assets", [])
                asset_url = None
                asset_name = None
                latest_tag = data.get("tag_name", "")

                for asset in assets:
                    if system in asset["name"].lower() and asset["name"].lower().endswith(".zip"):
                        asset_url = asset["browser_download_url"]
                        asset_name = asset["name"]
                        break

                if not asset_url:
                    await log("Could not find a matching zip release asset for this OS.")
                    return False

                await log(f"Downloading new release package: {asset_name}...")

                async with session.get(asset_url) as download_resp:
                    if download_resp.status == 200:
                        zip_path = "update_package.zip"
                        with open(zip_path, 'wb') as f:
                            f.write(await download_resp.read())

                        try:
                            extract_dir = "update_extracted"
                            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                zip_ref.extractall(extract_dir)

                            source_dir = extract_dir
                            if len(os.listdir(extract_dir)) == 1 and os.path.isdir(os.path.join(extract_dir, os.listdir(extract_dir)[0])):
                                source_dir = os.path.join(extract_dir, os.listdir(extract_dir)[0])

                            exe_path = sys.executable
                            exe_name = os.path.basename(exe_path)

                            for root, dirs, files in os.walk(source_dir):
                                rel_path = os.path.relpath(root, source_dir)
                                target_dir = os.path.join(os.getcwd(), rel_path) if rel_path != "." else os.getcwd()

                                os.makedirs(target_dir, exist_ok=True)

                                for file in files:
                                    src_file = os.path.join(root, file)
                                    # FIXED: Cross-platform executable detection
                                    if file == exe_name or (file.startswith("SoulClone") and (system == "windows" and "exe" in file or system != "windows")):
                                        new_exe_path = f"{exe_path}.new"
                                        shutil.copy2(src_file, new_exe_path)
                                        if os.path.exists(f"{exe_path}.old"):
                                            try:
                                                os.remove(f"{exe_path}.old")
                                            except OSError:
                                                pass
                                        shutil.move(exe_path, f"{exe_path}.old")
                                        shutil.move(new_exe_path, exe_path)
                                        if system != "windows":
                                            st = os.stat(exe_path)
                                            os.chmod(exe_path, st.st_mode | stat.S_IEXEC)
                                    else:
                                        target_file = os.path.join(target_dir, file)

                                        # Protect existing config.yaml from being overwritten by the update package
                                        if file == "config.yaml" and os.path.exists(target_file):
                                            target_file = target_file + ".update"

                                        shutil.copy2(src_file, target_file)

                            shutil.rmtree(extract_dir)
                            os.remove(zip_path)

                            # CRITICAL FIX: Patch the .env file with the new version to prevent infinite update loops
                            if latest_tag:
                                env_path = ".env"
                                if os.path.exists(env_path):
                                    with open(env_path, "r", encoding="utf-8") as f:
                                        lines = f.readlines()
                                    found = False
                                    with open(env_path, "w", encoding="utf-8") as f:
                                        for line in lines:
                                            if line.startswith("CURRENT_VERSION="):
                                                f.write(f'CURRENT_VERSION="{latest_tag}"\n')
                                                found = True
                                            else:
                                                f.write(line)
                                        if not found:
                                            f.write(f'CURRENT_VERSION="{latest_tag}"\n')

                        except Exception as e:
                            await log(f"Error during extraction and file swap: {e}")
                            return False
    else:
        process = await asyncio.create_subprocess_shell(
            "git pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            await log(f"Git pull failed:\n```\n{stderr.decode()}\n```")
            return False
        else:
            await log(f"Git pull successful:\n```\n{stdout.decode()}\n```")

    return True


def restart_process():
    """
    A direct approach to restarting PyInstaller apps or Python scripts.
    Since the updater renames the running executable to .old,
    the new executable is already in place. We can spawn it directly.
    """
    system = platform.system().lower()

    # Safely handle arguments as a list
    args = sys.argv[1:] if len(sys.argv) > 1 else ["bot"]

    if getattr(sys, 'frozen', False):
        exe_path = sys.executable

        # If for some reason we are running as .old, point to the real one
        if exe_path.endswith('.old'):
            exe_path = exe_path[:-4]

        cmd = [exe_path] + args
        exe_dir = os.path.dirname(exe_path)

        if system == "windows":
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                cwd=exe_dir,
                close_fds=True
            )
        else:
            subprocess.Popen(
                cmd,
                start_new_session=True,  # Modern replacement for preexec_fn=os.setpgrp
                cwd=exe_dir,
                close_fds=True
            )
    else:
        # Standard Python script restart
        cmd = [sys.executable] + sys.argv
        if system == "windows":
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True
            )
        else:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                close_fds=True
            )

    # Immediately kill the current process so the new one can take over
    os._exit(0)
