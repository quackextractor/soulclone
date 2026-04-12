import os
import sys
import platform
import aiohttp
import shutil
import stat
import zipfile
import asyncio


def toggle_autoupdate_env(new_state: bool):
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write(f"AUTOUPDATE={str(new_state)}\n")
        return

    with open(env_path, "r") as f:
        lines = f.readlines()

    found = False
    with open(env_path, "w") as f:
        for line in lines:
            if line.startswith("AUTOUPDATE="):
                f.write(f"AUTOUPDATE={str(new_state)}\n")
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f"AUTOUPDATE={str(new_state)}\n")


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
                                    if file == exe_name or (file.startswith("SoulClone") and "exe" in file):
                                        new_exe_path = f"{exe_path}.new"
                                        shutil.copy2(src_file, new_exe_path)
                                        if os.path.exists(f"{exe_path}.old"):
                                            os.remove(f"{exe_path}.old")
                                        shutil.move(exe_path, f"{exe_path}.old")
                                        shutil.move(new_exe_path, exe_path)
                                        if system != "windows":
                                            st = os.stat(exe_path)
                                            os.chmod(exe_path, st.st_mode | stat.S_IEXEC)
                                    else:
                                        target_file = os.path.join(target_dir, file)
                                        shutil.copy2(src_file, target_file)

                            shutil.rmtree(extract_dir)
                            os.remove(zip_path)

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
    env = os.environ.copy()
    env.pop('_MEIPASS2', None)
    env.pop('_MEIPASS', None)

    if getattr(sys, 'frozen', False):
        os.execve(sys.executable, sys.argv, env)
    else:
        os.execve(sys.executable, [sys.executable] + sys.argv, env)
