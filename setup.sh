#!/bin/bash
set -e

read -p "Enter your Discord bot token: " TOKEN
echo "DISCORD_TOKEN=$TOKEN" > .env
pip install -r requirements.txt

sudo tee /etc/systemd/system/minecraft-bot.service > /dev/null <<EOF
[Unit]
Description=Minecraft Discord Bot
After=network.target

[Service]
WorkingDirectory=$(pwd)
ExecStart=$(which python3) $(pwd)/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable minecraft-bot
sudo systemctl start minecraft-bot
echo "Bot is running!"
