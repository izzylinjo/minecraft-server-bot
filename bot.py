import asyncio
import os

import discord
from discord import app_commands
from dotenv import load_dotenv
from google.cloud import compute_v1

load_dotenv()

PROJECT = "project-6e30e75b-73f9-4256-ba7"
ZONE = "us-central1-c"
INSTANCE = "puresucc-mc-server"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
instances_client = compute_v1.InstancesClient()


def _get_status():
    return instances_client.get(project=PROJECT, zone=ZONE, instance=INSTANCE).status


def _start():
    instances_client.start(project=PROJECT, zone=ZONE, instance=INSTANCE)


def _stop():
    instances_client.stop(project=PROJECT, zone=ZONE, instance=INSTANCE)


@tree.command(name="startserver", description="Start the Minecraft server VM")
async def startserver(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status == "RUNNING":
        await interaction.followup.send("Server is already running.")
        return
    await asyncio.to_thread(_start)
    await interaction.followup.send("Starting server... give it ~1 minute to come up.")


@tree.command(name="stopserver", description="Stop the Minecraft server VM")
async def stopserver(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    if status == "TERMINATED":
        await interaction.followup.send("Server is already stopped.")
        return
    await asyncio.to_thread(_stop)
    await interaction.followup.send("Stopping server...")


@tree.command(name="serverstatus", description="Check the Minecraft server VM status")
async def serverstatus(interaction: discord.Interaction):
    await interaction.response.defer()
    status = await asyncio.to_thread(_get_status)
    await interaction.followup.send(f"Server status: **{status}**")


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")


client.run(os.getenv("DISCORD_TOKEN"))
