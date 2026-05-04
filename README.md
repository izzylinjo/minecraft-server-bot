# Minecraft Server Bot

A Discord bot that controls a Minecraft server running on a Google Cloud VM. Start, stop, and restart the server directly from Discord.

## Commands

| Command | Description |
|---|---|
| `/startserver` | Starts the VM and the Minecraft server |
| `/stopserver` | Safely stops Minecraft (saves the world), then shuts down the VM |
| `/startmc` | Starts only the Minecraft server (VM must already be on) |
| `/stopmc` | Stops only the Minecraft server (VM stays on) |
| `/restartserver` | Restarts only the Minecraft server (VM stays on) |
| `/serverstatus` | Shows the current VM status |

The bot sends step-by-step updates in Discord — it will tell you when the VM is up, when Minecraft is ready to join, and when everything is fully offline.

## Requirements

- A Google Cloud VM running the Minecraft server
- A second GCP VM to run this bot (free tier e2-micro works)
- A Discord bot token

## Setup

### 1. Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a new application → go to **Bot** → copy the token
3. Under **OAuth2 → URL Generator**, select `bot` + `applications.commands`, then invite it to your server

### 2. Minecraft VM

The Minecraft server must start automatically on boot. SSH into your Minecraft VM and run this once:

```bash
sudo tee /etc/systemd/system/minecraft.service > /dev/null <<EOF
[Unit]
Description=Minecraft Server
After=network.target

[Service]
WorkingDirectory=/opt/minecraft
ExecStart=/usr/bin/screen -dmS minecraft ./run.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable minecraft
```

### 3. Bot VM

SSH into the bot VM and run:

```bash
git clone https://github.com/izzylinjo/minecraft-server-bot.git
cd minecraft-server-bot
chmod +x setup.sh
./setup.sh
```

It will prompt you for your Discord bot token and handle everything else automatically.

**Note:** The bot VM's service account needs the **Compute Instance Admin (v1)** IAM role to start/stop the Minecraft VM. It also needs `gcloud` installed (`apt install google-cloud-cli`) to send commands to the Minecraft VM.

## How it works

- **GCP authentication** is handled automatically via Application Default Credentials — no JSON key file needed.
- **VM control** uses the `google-cloud-compute` Python library.
- **Minecraft control** uses `gcloud compute ssh` to send commands to the Minecraft VM's screen session.
- The bot polls port `25565` to detect when Minecraft is actually ready, not just when the VM boots.
