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


def _stop_mc():
    try:
        _ssh("sudo screen -S minecraft -X stuff $'stop\\n'")
    except subprocess.CalledProcessError:
        pass  # session not found means MC is already stopped


def _start_mc():
    _ssh("cd /opt/minecraft && sudo screen -dmS minecraft ./run.sh")


def _port_open(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=3):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


async def _wait_for_port(ip, open: bool):
    while True:
        result = await asyncio.to_thread(_port_open, ip, MC_PORT)
        if result == open:
            break
        await asyncio.sleep(5)


async def _wait_for_vm_status(target: str):
    while True:
        status = await asyncio.to_thread(_get_status)
        if status == target:
            break
        await asyncio.sleep(5)


async def _start_and_notify(channel: discord.TextChannel):
    await _wait_for_vm_status("RUNNING")
    ip = await asyncio.to_thread(_get_ip)
    await channel.send("VM is up! Starting Minecraft...")
    await asyncio.to_thread(_start_mc)
    await _wait_for_port(ip, open=True)
    await channel.send(f"Minecraft server is ready! Connect to: **{ip}**")


async def _stop_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    await _wait_for_port(ip, open=False)
    await channel.send("Minecraft stopped. Shutting down VM...")
    await asyncio.to_thread(_stop_vm)
    await _wait_for_vm_status("TERMINATED")
    await channel.send("Server is fully offline.")


async def _wait_mc_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    await _wait_for_port(ip, open=True)
    await channel.send(f"Minecraft server is ready! Connect to: **{ip}**")


async def _wait_mc_stop_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    await _wait_for_port(ip, open=False)
    await channel.send("Minecraft server stopped. VM is still running.")


async def _restart_and_notify(channel: discord.TextChannel):
    ip = await asyncio.to_thread(_get_ip)
    await _wait_for_port(ip, open=False)
    await channel.send("Minecraft stopped. Starting it back up...")
    await asyncio.to_thread(_start_mc)
    await _wait_for_port(ip, open=True)
    await channel.send(f"Minecraft server is back up! Connect to: **{ip}**")


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
    await asyncio.to_thread(_stop_mc)
    await interaction.followup.send("Stopping Minecraft server... waiting for it to save.")
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
