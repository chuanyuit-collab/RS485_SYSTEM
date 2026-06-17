#!/bin/bash

TARGET_DIR="/home/cys/prog/RS485_SYSTEM"
cd $TARGET_DIR

echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "Installing requirements..."
pip install -r requirements.txt

echo "Setting up systemd service..."
sudo cp rs485_dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable rs485_dashboard
sudo systemctl restart rs485_dashboard

echo "Setup and deployment completed successfully."
echo "Service status:"
sudo systemctl status rs485_dashboard --no-pager
