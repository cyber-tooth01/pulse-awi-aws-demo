#!/bin/bash
# EC2 User Data Script - Automatic setup of PulseAQI MQTT Bridge

# Update system
apt-get update
apt-get upgrade -y

# Install Python and pip
apt-get install -y python3-pip git

# Install required Python packages
pip3 install paho-mqtt boto3

# Create application directory
mkdir -p /opt/pulseaqi
cd /opt/pulseaqi

# Note: mqtt_bridge.py should be embedded here or fetched from S3
# For now, this expects you to manually upload the script after instance launch

# Create systemd service
cat > /etc/systemd/system/pulseaqi-mqtt.service << 'EOF'
[Unit]
Description=PulseAQI MQTT to Timestream Bridge
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/pulseaqi
ExecStart=/usr/bin/python3 /opt/pulseaqi/mqtt_bridge.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable service (will start once mqtt_bridge.py is uploaded)
systemctl daemon-reload
systemctl enable pulseaqi-mqtt

echo "PulseAQI setup complete. Upload mqtt_bridge.py to /opt/pulseaqi/ and run: sudo systemctl start pulseaqi-mqtt"
