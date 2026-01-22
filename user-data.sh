#!/bin/bash
# EC2 User Data Script - Automatic setup of PulseAQI MQTT Bridge

# Update system
apt-get update
apt-get upgrade -y

# Install Python and pip
apt-get install -y python3-pip git

# Install required Python packages
pip3 install paho-mqtt influxdb-client meshtastic

# Create application directory
mkdir -p /opt/pulseaqi
cd /opt/pulseaqi

# Note: mqtt_bridge.py should be embedded here or fetched from S3
# For now, this expects you to manually upload the script after instance launch
# You must also set environment variables: INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET

# Create systemd service
cat > /etc/systemd/system/pulseaqi-mqtt.service << 'EOF'
[Unit]
Description=PulseAQI MQTT to InfluxDB Bridge
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/pulseaqi
Environment="INFLUXDB_TOKEN=<your_token>"
Environment="INFLUXDB_ORG=<your_org>"
Environment="INFLUXDB_BUCKET=pulseaqi"
Environment="INFLUXDB_URL=https://us-east-1-1.aws.cloud2.influxdata.com"
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
