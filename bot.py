import asyncio
import os
import socket
import subprocess

import discord
from discord import app_commands
from dotenv import load_dotenv
from google.cloud import compute_v1

load_dotenv()

PROJECT = "project-6e30e75b-73f9-4256-ba7"
ZONE = "us-central1-c"
INSTANCE = "puresucc-mc-server"
MC_PORT = 25565

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
instances_client = compute_v1.InstancesClient()


def _get_instance():
    return instances_client.get(project=PROJECT, zone=ZONE, instance=INSTANCE)


def _get_status():
    return _get_instance().status


def _get_ip():
    return _get_instance().network_interfaces[0].access_configs[0].nat_i_p


def _start_vm():
    instances_client.start(project=PROJECT, zone=ZONE, instance=INSTANCE)


def _stop_vm():
    instances_client.stop(project=PROJECT, zone=ZONE, instance=INSTANCE)


def _ssh(command):
    subprocess.run([
        "gcloud", "compute", "ssh", INSTANCE,
        f"--zone={ZONE}", f"--project={PROJECT}",
        f"--command={command}", "--quiet"
    ], check=True)


def _get_packs():
    result = subprocess.run([
        "gcloud", "compute", "ssh", INSTANCE,
        f"--zone={ZONE}", f"--project={PROJECT}",
        "--command=ls /opt/ | grep ^minecraft-", "--quiet"
    ], capture_output=True, text=True)
    folders = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    return {f.removeprefix("minecraft-"): f"/opt/{f}" for f in folders}


def _get_current_pack():
    result = subprocess.run([
        "gcloud", "compute", "ssh", INSTANCE,
        f"--zone={ZONE}", f"--project={PROJECT}",
        "--command=readlink /opt/minecraft", "--quiet"
    ], capture_output=True, text=True)
    target = result.stdout.strip()
    return target.removeprefix("/opt/minecraft-") if target else None


def _swap_pack(path):
    _ssh(f"sudo ln -sfn {path} /opt/minecraft")


def _stop_mc():
    try:
        _ssh("sudo screen -S minecraft -X stuff $'stop\\n'")
    except subprocess.CalledProcessError:
        pass  # session not found means MC is already stopped


def _start_mc():
    _ssh("sudo screen -dmS minecraft bash -c 'cd /opt/minecraft && ./run.sh nogui'")


def _port_open(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=3):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


async def _wait_for_port(ip, open: bool, timeout: int = None):
    elapsed = 0
    while True:
        result = await asyncio.to_thread(_port_open, ip, MC_PORT)
        if result == open:
            break
        if timeout is not None and elapsed >= timeout:
            break
        await asyncio.sleep(5)
        elapsed += 5


async def _safe_send(channel, msg):
    try:
        await channel.send(msg)
    except discord.HTTPException:
        pass


async def _wait_for_vm_status(target: str):
    while True:
        status = await asyncio.to_thread(_get_status)
        if status == target:
            break
        await asyncio.sleep(5)


async def _start_and_notify(channel: discord.TextChannel):
    await _wait_for_vm_status("RUNNING")
    ip = await asyncio.to_thread(_get_ip)
    pack = await asyncio.to_thread(_get_current_pack)
    pack_label = f"**{pack}**" if pack else "Minecraft"
    await _safe_send(channel, f"VM is up! Starting {pack_label}...")
    await asyncio.to_thread(_start_mc)
    await _wait_for_port(ip, open=True)
    await _safe_send(channel, f"{pack_label} is ready! Connect to: **{ip}**")


async def _stop_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    await _wait_for_port(ip, open=False, timeout=180)
    await asyncio.to_thread(_stop_vm)
    await _safe_send(channel, "Minecraft stopped. Shutting down VM...")
    await _wait_for_vm_status("TERMINATED")
    await _safe_send(channel, "Server is fully offline.")


async def _wait_mc_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    pack = await asyncio.to_thread(_get_current_pack)
    pack_label = f"**{pack}**" if pack else "Minecraft"
    await _wait_for_port(ip, open=True)
    await _safe_send(channel, f"{pack_label} is ready! Connect to: **{ip}**")


async def _wait_mc_stop_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    await _wait_for_port(ip, open=False, timeout=180)
    await _safe_send(channel, "Minecraft server stopped. VM is still running.")


async def _restart_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    pack = await asyncio.to_thread(_get_current_pack)
    pack_label = f"**{pack}**" if pack else "Minecraft"
    await _wait_for_port(ip, open=False, timeout=180)
    await asyncio.to_thread(_start_mc)
    await _safe_send(channel, f"Stopped. Starting {pack_label} back up...")
    await _wait_for_port(ip, open=True)
    await _safe_send(channel, f"{pack_label} is back up! Connect to: **{ip}**")


class SwapConfirmView(discord.ui.View):
    def __init__(self, pack_name, pack_path, ip):
        super().__init__(timeout=30)
        self.pack_name = pack_name
        self.pack_path = pack_path
        self.ip = ip

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content=f"Stopping Minecraft and switching to **{self.pack_name}**...", view=None)
        await asyncio.to_thread(_stop_mc)
        await _wait_for_port(self.ip, open=False, timeout=180)
        await asyncio.to_thread(_swap_pack, self.pack_path)
        await asyncio.to_thread(_start_mc)
        await interaction.channel.send(f"Switched to **{self.pack_name}**. Starting server...")
        await _wait_for_port(self.ip, open=True)
        await interaction.channel.send(f"Minecraft is ready on **{self.pack_name}**! Connect to: **{self.ip}**")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Pack swap cancelled.", view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class PackSelect(discord.ui.Select):
    def __init__(self, packs, current_pack):
        options = [
            discord.SelectOption(label=name, description=path)
            for name, path in packs.items()
            if name != current_pack
        ]
        super().__init__(placeholder="Choose a modpack...", options=options)
        self.packs = packs
        self.current_pack = current_pack

    async def callback(self, interaction: discord.Interaction):
        pack_name = self.values[0]
        pack_path = self.packs[pack_name]
        await interaction.response.defer()
        vm_status = await asyncio.to_thread(_get_status)
        if vm_status != "RUNNING":
            await asyncio.to_thread(_swap_pack, pack_path)
            await interaction.followup.send(f"Switched to **{pack_name}**. Start the server when ready.")
            return
        ip = await asyncio.to_thread(_get_ip)
        mc_running = await asyncio.to_thread(_port_open, ip, MC_PORT)
        if not mc_running:
            await asyncio.to_thread(_swap_pack, pack_path)
            await interaction.followup.send(f"Switched to **{pack_name}**. Use /startmc to start it.")
            return
        view = SwapConfirmView(pack_name, pack_path, ip)
        await interaction.followup.send(
            f"⚠️ Minecraft is currently running. Switching to **{pack_name}** will stop it. Continue?",
            view=view
        )


class PackSelectView(discord.ui.View):
    def __init__(self, packs, current_pack):
        super().__init__()
        self.add_item(PackSelect(packs, current_pack))


@tree.command(name="switchpack", description="Switch the active modpack")
async def switchpack(interaction: discord.Interaction):
    await interaction.response.defer()
    vm_status = await asyncio.to_thread(_get_status)
    packs = await asyncio.to_thread(_get_packs)
    if not packs:
        await interaction.followup.send("No modpack folders found under /opt/minecraft-*")
        return
    current = await asyncio.to_thread(_get_current_pack)
    if vm_status == "RUNNING":
        current_line = f"Currently running: **{current}**\n" if current else ""
    else:
        current_line = f"Currently set to: **{current}**\n" if current else ""
    if len(packs) == 1 and list(packs.keys())[0] == current:
        await interaction.followup.send("Only one modpack is installed and it's already active.")
        return
    view = PackSelectView(packs, current)
    await interaction.followup.send(f"{current_line}Select a modpack to switch to:", view=view)


@tree.command(name="startmc", description="Start only the Minecraft server (VM must already be on)")
async def startmc(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status != "RUNNING":
        await interaction.followup.send("VM is not running. Use /startserver first.")
        return
    ip = await asyncio.to_thread(_get_ip)
    if await asyncio.to_thread(_port_open, ip, MC_PORT):
        await interaction.followup.send("Minecraft is already running.")
        return
    await asyncio.to_thread(_start_mc)
    await interaction.followup.send("Starting Minecraft server...")
    asyncio.create_task(_wait_mc_and_notify(interaction.channel))


@tree.command(name="stopmc", description="Stop only the Minecraft server (VM stays on)")
async def stopmc(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status != "RUNNING":
        await interaction.followup.send("VM is not running.")
        return
    ip = await asyncio.to_thread(_get_ip)
    if not await asyncio.to_thread(_port_open, ip, MC_PORT):
        await interaction.followup.send("Minecraft is already stopped.")
        return
    await asyncio.to_thread(_stop_mc)
    await interaction.followup.send("Stopping Minecraft server... waiting for it to save.")
    asyncio.create_task(_wait_mc_stop_and_notify(interaction.channel))


@tree.command(name="startserver", description="Start the Minecraft server VM")
async def startserver(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status == "RUNNING":
        await interaction.followup.send("Server is already running.")
        return
    await asyncio.to_thread(_start_vm)
    await interaction.followup.send("Starting server...")
    asyncio.create_task(_start_and_notify(interaction.channel))


@tree.command(name="stopserver", description="Stop the Minecraft server and VM")
async def stopserver(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status == "TERMINATED":
        await interaction.followup.send("Server is already stopped.")
        return
    ip = await asyncio.to_thread(_get_ip)
    mc_running = await asyncio.to_thread(_port_open, ip, MC_PORT)
    if mc_running:
        await asyncio.to_thread(_stop_mc)
        await interaction.followup.send("Stopping Minecraft server... waiting for it to save.")
    else:
        await interaction.followup.send("Minecraft is already off. Shutting down VM...")
    asyncio.create_task(_stop_and_notify(interaction.channel))


@tree.command(name="restartserver", description="Restart the Minecraft server (VM stays on)")
async def restartserver(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status != "RUNNING":
        await interaction.followup.send("VM is not running. Use /startserver first.")
        return
    await asyncio.to_thread(_stop_mc)
    await interaction.followup.send("Restarting Minecraft server...")
    asyncio.create_task(_restart_and_notify(interaction.channel))


@tree.command(name="command", description="Run a command on the Minecraft server console")
@app_commands.describe(cmd="The Minecraft command to run (without the /)")
async def command(interaction: discord.Interaction, cmd: str):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status != "RUNNING":
        await interaction.followup.send("Server is not running.")
        return
    await asyncio.to_thread(_ssh, f"screen -S minecraft -X stuff $'{cmd}\\n'")
    await interaction.followup.send(f"Ran command: `{cmd}`")


@tree.command(name="serverstatus", description="Check the Minecraft server VM status")
async def serverstatus(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    await interaction.followup.send(f"VM status: **{status}**")


@tree.command(name="mcstatus", description="Check if the Minecraft server is running")
async def mcstatus(interaction: discord.Interaction):
    await interaction.response.defer()
    vm_status = await asyncio.to_thread(_get_status)
    if vm_status != "RUNNING":
        await interaction.followup.send("Minecraft server is **offline** (VM is not running).")
        return
    ip = await asyncio.to_thread(_get_ip)
    up = await asyncio.to_thread(_port_open, ip, MC_PORT)
    if up:
        await interaction.followup.send(f"Minecraft server is **online**! Connect to: **{ip}**")
    else:
        await interaction.followup.send("VM is running but Minecraft is **offline**.")


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")


client.run(os.getenv("DISCORD_TOKEN"))
