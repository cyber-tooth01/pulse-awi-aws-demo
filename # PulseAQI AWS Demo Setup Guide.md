# PulseAQI AWS Demo Setup Guide

**Quick demo infrastructure for Meshtastic-based air quality monitoring**

**Timeline:** 4-6 hours  
**Cost:** ~$3/month for 5 nodes  
**Goal:** Impressive live dashboard for presentation

---

## Architecture Overview

```
Meshtastic Mesh Network (LoRa)
    ↓
MQTT Bridge Node (Ethernet-connected)
    ↓
mqtt.meshtastic.org or Private Broker
    ↓
AWS EC2 t2.micro (MQTT → Timestream Bridge)
    ↓
Amazon Timestream (Time-series Database)
    ↓
Grafana Cloud (Free Tier) - Live Dashboard
```

**Your MQTT Topic:** `msh/US/2/e/pulse-aqi/#`

**Data Format:**
```json
{
  "id": "123456789",
  "sender": "!e70287b5",
  "type": "text",
  "payload": {
    "text": "{\"pm1\":3,\"pm25\":4,\"pm4\":5,\"pm10\":5,\"voc\":103.0,\"nox\":1.0,\"t\":24.7,\"rh\":63.8}"
  }
}
```

---

## Prerequisites

### 1. AWS Account Setup
```bash
# Install AWS CLI
# Windows: https://aws.amazon.com/cli/
# Mac: brew install awscli
# Linux: sudo apt install awscli

# Configure credentials
aws configure
# AWS Access Key ID: [your key]
# AWS Secret Access Key: [your secret]
# Default region: us-east-1
# Default output format: json
```

### 2. Required IAM Permissions

Create IAM user `pulseaqi-admin` with policies:
- `AmazonTimestreamFullAccess`
- `AmazonEC2FullAccess`
- `IAMFullAccess` (to create roles)
- `CloudWatchLogsFullAccess`

### 3. Python Libraries (for local testing)
```bash
pip install paho-mqtt boto3
```

---

## Part 1: AWS Timestream Database Setup

### Create Database and Table

```bash
# Set variables
export AWS_REGION=us-east-1
export DATABASE_NAME=pulseaqi_demo
export TABLE_NAME=sensor_data

# Create database
aws timestream-write create-database \
  --database-name $DATABASE_NAME \
  --region $AWS_REGION

# Create table with 24-hour memory retention, 7-day magnetic storage
aws timestream-write create-table \
  --database-name $DATABASE_NAME \
  --table-name $TABLE_NAME \
  --retention-properties "MemoryStoreRetentionPeriodInHours=24,MagneticStoreRetentionPeriodInDays=7" \
  --region $AWS_REGION

# Verify creation
aws timestream-write describe-table \
  --database-name $DATABASE_NAME \
  --table-name $TABLE_NAME \
  --region $AWS_REGION
```

**Expected Output:**
```json
{
    "Table": {
        "Arn": "arn:aws:timestream:us-east-1:...",
        "TableName": "sensor_data",
        "DatabaseName": "pulseaqi_demo",
        "TableStatus": "ACTIVE"
    }
}
```

---

## Part 2: EC2 Instance Setup (MQTT Bridge)

### Create IAM Role for EC2

```bash
# Create trust policy for EC2
cat > ec2-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create role
aws iam create-role \
  --role-name pulseaqi-ec2-role \
  --assume-role-policy-document file://ec2-trust-policy.json

# Create policy for Timestream access
cat > timestream-write-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "timestream:WriteRecords",
        "timestream:DescribeEndpoints"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Attach policy to role
aws iam put-role-policy \
  --role-name pulseaqi-ec2-role \
  --policy-name timestream-write-policy \
  --policy-document file://timestream-write-policy.json

# Create instance profile
aws iam create-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile

# Add role to instance profile
aws iam add-role-to-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile \
  --role-name pulseaqi-ec2-role

# Wait 10 seconds for IAM to propagate
sleep 10
```

### Launch EC2 Instance

```bash
# Create security group
aws ec2 create-security-group \
  --group-name pulseaqi-mqtt-bridge \
  --description "Security group for PulseAQI MQTT bridge" \
  --region $AWS_REGION

# Get security group ID
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=pulseaqi-mqtt-bridge" \
  --query "SecurityGroups[0].GroupId" \
  --output text)

# Allow SSH access (replace YOUR_IP with your IP address)
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32

# Launch EC2 instance (t2.micro - free tier eligible)
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --count 1 \
  --instance-type t2.micro \
  --key-name YOUR_KEY_PAIR_NAME \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=pulseaqi-ec2-profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=pulseaqi-mqtt-bridge}]' \
  --user-data file://user-data.sh \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "Instance ID: $INSTANCE_ID"

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# Get instance public IP
PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo "Instance Public IP: $PUBLIC_IP"
```

### User Data Script (Automatic Setup)

Create `user-data.sh`:

```bash
#!/bin/bash

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

# Create MQTT bridge script (see mqtt_bridge.py below)
cat > mqtt_bridge.py << 'PYEOF'
# Script content will be inserted here
PYEOF

# Create systemd service
cat > /etc/systemd/system/pulseaqi-mqtt.service << 'SVCEOF'
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

[Install]
WantedBy=multi-user.target
SVCEOF

# Enable and start service
systemctl daemon-reload
systemctl enable pulseaqi-mqtt
systemctl start pulseaqi-mqtt
```

---

## Part 3: MQTT Bridge Application Code

### Main Application: `mqtt_bridge.py`

```python
#!/usr/bin/env python3
"""
PulseAQI MQTT to Timestream Bridge
Subscribes to Meshtastic MQTT, parses sensor data, writes to AWS Timestream
"""

import json
import boto3
import paho.mqtt.client as mqtt
from datetime import datetime
import logging
import sys
import time

# Configuration
MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_TOPIC = "msh/US/2/e/pulse-aqi/#"

AWS_REGION = "us-east-1"
DATABASE_NAME = "pulseaqi_demo"
TABLE_NAME = "sensor_data"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/pulseaqi-mqtt.log')
    ]
)
logger = logging.getLogger(__name__)

# Initialize Timestream client
timestream = boto3.client('timestream-write', region_name=AWS_REGION)

def calculate_aqi_pm25(pm25):
    """
    Calculate AQI from PM2.5 using EPA breakpoints
    Returns integer AQI value
    """
    if pm25 <= 12.0:
        return int((50 - 0) / (12.0 - 0.0) * (pm25 - 0.0) + 0)
    elif pm25 <= 35.4:
        return int((100 - 51) / (35.4 - 12.1) * (pm25 - 12.1) + 51)
    elif pm25 <= 55.4:
        return int((150 - 101) / (55.4 - 35.5) * (pm25 - 35.5) + 101)
    elif pm25 <= 150.4:
        return int((200 - 151) / (150.4 - 55.5) * (pm25 - 55.5) + 151)
    elif pm25 <= 250.4:
        return int((300 - 201) / (250.4 - 150.5) * (pm25 - 150.5) + 201)
    else:
        return int((500 - 301) / (500.4 - 250.5) * (pm25 - 250.5) + 301)

def get_aqi_category(aqi):
    """Return AQI category string"""
    if aqi <= 50:
        return "Good"
    elif aqi <= 100:
        return "Moderate"
    elif aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    elif aqi <= 200:
        return "Unhealthy"
    elif aqi <= 300:
        return "Very Unhealthy"
    else:
        return "Hazardous"

def make_timestream_record(node_id, metric_name, value, timestamp):
    """Create a Timestream record"""
    return {
        'Dimensions': [
            {'Name': 'node_id', 'Value': node_id},
            {'Name': 'metric', 'Value': metric_name}
        ],
        'MeasureName': 'value',
        'MeasureValue': str(value),
        'MeasureValueType': 'DOUBLE',
        'Time': timestamp
    }

def write_to_timestream(records):
    """Write records to Timestream with retry logic"""
    try:
        result = timestream.write_records(
            DatabaseName=DATABASE_NAME,
            TableName=TABLE_NAME,
            Records=records
        )
        logger.info(f"✓ Wrote {len(records)} records to Timestream")
        return True
    except timestream.exceptions.RejectedRecordsException as e:
        logger.error(f"Some records rejected: {e}")
        return False
    except Exception as e:
        logger.error(f"Error writing to Timestream: {e}")
        return False

def on_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        logger.info(f"✓ Connected to MQTT broker: {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        logger.info(f"✓ Subscribed to topic: {MQTT_TOPIC}")
    else:
        logger.error(f"✗ Connection failed with code {rc}")

def on_disconnect(client, userdata, rc):
    """MQTT disconnection callback"""
    if rc != 0:
        logger.warning(f"Unexpected disconnect. Will attempt reconnect...")

def on_message(client, userdata, msg):
    """MQTT message callback - main processing logic"""
    try:
        # Parse MQTT message
        payload = json.loads(msg.payload.decode())
        
        # Log raw message for debugging
        logger.debug(f"Received from {msg.topic}: {json.dumps(payload, indent=2)}")
        
        # Check if this is a text message with sensor data
        if payload.get('type') != 'text':
            logger.debug(f"Skipping non-text message type: {payload.get('type')}")
            return
        
        # Extract node ID
        node_id = payload.get('sender', 'unknown')
        if node_id == 'unknown':
            logger.warning("Message missing sender field")
            return
        
        # Parse sensor JSON from text field
        sensor_text = payload.get('payload', {}).get('text', '')
        if not sensor_text.startswith('{'):
            logger.debug(f"Text message is not JSON: {sensor_text[:50]}")
            return
        
        sensor_data = json.loads(sensor_text)
        
        # Validate required fields
        required_fields = ['pm1', 'pm25', 'pm4', 'pm10', 'voc', 'nox', 't', 'rh']
        if not all(field in sensor_data for field in required_fields):
            logger.warning(f"Missing required sensor fields in: {sensor_data}")
            return
        
        # Calculate AQI
        pm25 = float(sensor_data['pm25'])
        aqi = calculate_aqi_pm25(pm25)
        category = get_aqi_category(aqi)
        
        logger.info(f"📊 Node {node_id}: AQI={aqi} ({category}), PM2.5={pm25} µg/m³")
        
        # Prepare Timestream records
        current_time = str(int(datetime.utcnow().timestamp() * 1000))
        
        records = [
            make_timestream_record(node_id, 'pm1', sensor_data['pm1'], current_time),
            make_timestream_record(node_id, 'pm25', sensor_data['pm25'], current_time),
            make_timestream_record(node_id, 'pm4', sensor_data['pm4'], current_time),
            make_timestream_record(node_id, 'pm10', sensor_data['pm10'], current_time),
            make_timestream_record(node_id, 'voc', sensor_data['voc'], current_time),
            make_timestream_record(node_id, 'nox', sensor_data['nox'], current_time),
            make_timestream_record(node_id, 'temp', sensor_data['t'], current_time),
            make_timestream_record(node_id, 'humidity', sensor_data['rh'], current_time),
            make_timestream_record(node_id, 'aqi', aqi, current_time),
        ]
        
        # Write to Timestream
        write_to_timestream(records)
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)

def main():
    """Main application loop"""
    logger.info("=" * 60)
    logger.info("PulseAQI MQTT to Timestream Bridge Starting")
    logger.info(f"MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"MQTT Topic: {MQTT_TOPIC}")
    logger.info(f"Timestream: {DATABASE_NAME}.{TABLE_NAME}")
    logger.info("=" * 60)
    
    # Create MQTT client
    client = mqtt.Client(client_id="pulseaqi-bridge")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    
    # Connect with retry logic
    while True:
        try:
            logger.info(f"Connecting to MQTT broker...")
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as e:
            logger.error(f"Connection failed: {e}. Retrying in 10 seconds...")
            time.sleep(10)
    
    # Start MQTT loop
    logger.info("Starting MQTT loop...")
    client.loop_forever()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
```

### Deploy to EC2

```bash
# SSH into instance
ssh -i YOUR_KEY.pem ubuntu@$PUBLIC_IP

# Upload the Python script
scp -i YOUR_KEY.pem mqtt_bridge.py ubuntu@$PUBLIC_IP:/opt/pulseaqi/

# On EC2 instance, create systemd service
sudo tee /etc/systemd/system/pulseaqi-mqtt.service > /dev/null << 'EOF'
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

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable pulseaqi-mqtt
sudo systemctl start pulseaqi-mqtt

# Check status
sudo systemctl status pulseaqi-mqtt

# View live logs
sudo journalctl -u pulseaqi-mqtt -f
```

**Expected Log Output:**
```
Jan 18 14:23:45 INFO: ✓ Connected to MQTT broker: mqtt.meshtastic.org
Jan 18 14:23:45 INFO: ✓ Subscribed to topic: msh/US/2/e/pulse-aqi/#
Jan 18 14:23:52 INFO: 📊 Node !e70287b5: AQI=42 (Good), PM2.5=10.5 µg/m³
Jan 18 14:23:52 INFO: ✓ Wrote 9 records to Timestream
```

---

## Part 4: Grafana Cloud Setup

### 1. Create Free Account
- Go to: https://grafana.com/auth/sign-up/create-user
- Sign up with email
- Choose "Free Forever" tier (10k metrics, 14-day retention)

### 2. Add Timestream Data Source

```bash
# In Grafana UI:
# 1. Click "Connections" → "Data sources" → "Add data source"
# 2. Search "Timestream"
# 3. Configure:

# Settings:
Name: AWS Timestream - PulseAQI
Default Region: us-east-1
Authentication Provider: Access & secret key
Access Key ID: [Your AWS Access Key]
Secret Access Key: [Your AWS Secret Key]

# Click "Save & Test"
```

### 3. Import Dashboard

Save this as `pulseaqi-dashboard.json`:

```json
{
  "dashboard": {
    "title": "PulseAQI - Live Air Quality Monitor",
    "uid": "pulseaqi-live",
    "timezone": "browser",
    "refresh": "10s",
    "time": {
      "from": "now-1h",
      "to": "now"
    },
    "panels": [
      {
        "id": 1,
        "title": "Current AQI by Node",
        "type": "stat",
        "gridPos": {"x": 0, "y": 0, "w": 24, "h": 6},
        "targets": [{
          "datasource": "AWS Timestream - PulseAQI",
          "queryType": "timestream",
          "rawQuery": "SELECT node_id, MAX(measure_value::double) as aqi FROM \"pulseaqi_demo\".\"sensor_data\" WHERE measure_name = 'value' AND dimension_metric = 'aqi' AND time > ago(2m) GROUP BY node_id"
        }],
        "fieldConfig": {
          "defaults": {
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"value": 0, "color": "green"},
                {"value": 51, "color": "yellow"},
                {"value": 101, "color": "orange"},
                {"value": 151, "color": "red"}
              ]
            },
            "unit": "none"
          }
        }
      },
      {
        "id": 2,
        "title": "PM2.5 Levels (Last 24 Hours)",
        "type": "timeseries",
        "gridPos": {"x": 0, "y": 6, "w": 12, "h": 8},
        "targets": [{
          "datasource": "AWS Timestream - PulseAQI",
          "queryType": "timestream",
          "rawQuery": "SELECT time, node_id, measure_value::double as pm25 FROM \"pulseaqi_demo\".\"sensor_data\" WHERE measure_name = 'value' AND dimension_metric = 'pm25' AND time > ago(24h) ORDER BY time DESC"
        }]
      },
      {
        "id": 3,
        "title": "AQI Trend",
        "type": "timeseries",
        "gridPos": {"x": 12, "y": 6, "w": 12, "h": 8},
        "targets": [{
          "datasource": "AWS Timestream - PulseAQI",
          "queryType": "timestream",
          "rawQuery": "SELECT time, node_id, measure_value::double as aqi FROM \"pulseaqi_demo\".\"sensor_data\" WHERE measure_name = 'value' AND dimension_metric = 'aqi' AND time > ago(24h) ORDER BY time DESC"
        }]
      },
      {
        "id": 4,
        "title": "All Pollutants - Latest Reading",
        "type": "table",
        "gridPos": {"x": 0, "y": 14, "w": 24, "h": 8},
        "targets": [{
          "datasource": "AWS Timestream - PulseAQI",
          "queryType": "timestream",
          "rawQuery": "SELECT node_id, MAX(CASE WHEN dimension_metric = 'pm25' THEN measure_value::double END) as PM2_5, MAX(CASE WHEN dimension_metric = 'pm10' THEN measure_value::double END) as PM10, MAX(CASE WHEN dimension_metric = 'voc' THEN measure_value::double END) as VOC, MAX(CASE WHEN dimension_metric = 'nox' THEN measure_value::double END) as NOx, MAX(CASE WHEN dimension_metric = 'temp' THEN measure_value::double END) as Temp_C, MAX(CASE WHEN dimension_metric = 'humidity' THEN measure_value::double END) as Humidity_Pct, MAX(CASE WHEN dimension_metric = 'aqi' THEN measure_value::double END) as AQI FROM \"pulseaqi_demo\".\"sensor_data\" WHERE time > ago(2m) GROUP BY node_id"
        }]
      }
    ]
  }
}
```

**Import in Grafana:**
1. Click "Dashboards" → "Import"
2. Paste JSON above or upload file
3. Select data source: "AWS Timestream - PulseAQI"
4. Click "Import"

---

## Part 5: Testing & Verification

### Test MQTT Connection Locally

```bash
# Install mosquitto client
sudo apt install mosquitto-clients  # Linux
brew install mosquitto              # Mac

# Subscribe to your topic
mosquitto_sub -h mqtt.meshtastic.org -t "msh/US/2/e/pulse-aqi/#" -v

# You should see messages like:
# msh/US/2/e/pulse-aqi/!e70287b5 {"sender":"!e70287b5","type":"text",...}
```

### Query Timestream Directly

```bash
# Test query
aws timestream-query query \
  --query-string "SELECT * FROM \"pulseaqi_demo\".\"sensor_data\" WHERE time > ago(10m) ORDER BY time DESC LIMIT 10" \
  --region us-east-1

# Count records per node
aws timestream-query query \
  --query-string "SELECT node_id, COUNT(*) as record_count FROM \"pulseaqi_demo\".\"sensor_data\" GROUP BY node_id" \
  --region us-east-1
```

### Check EC2 Logs

```bash
# SSH to EC2
ssh -i YOUR_KEY.pem ubuntu@$PUBLIC_IP

# Check service status
sudo systemctl status pulseaqi-mqtt

# View logs
sudo journalctl -u pulseaqi-mqtt -f --since "10 minutes ago"

# Check for errors
sudo journalctl -u pulseaqi-mqtt -p err
```

---

## Part 6: Presentation Prep

### Dashboard Enhancements

**Add Annotations:**
1. In Grafana, click any graph
2. Click annotation icon
3. Add text: "Sensor deployment started"
4. Shows as vertical line on graphs

**Set Up Alerts (Optional):**
```
Alert Name: High AQI Warning
Condition: WHEN avg() OF query(A, 5m, now) IS ABOVE 100
Send to: Email / Slack
Message: "AQI exceeded 100 on node ${node_id}"
```

### Cost Dashboard

```bash
# Get current month costs
aws ce get-cost-and-usage \
  --time-period Start=$(date -d "-7 days" +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --metrics "UnblendedCost" \
  --group-by Type=SERVICE \
  --filter file://<(echo '{
    "Tags": {
      "Key": "Project",
      "Values": ["PulseAQI"]
    }
  }')
```

### Demo Script

**Opening (30 seconds):**
> "We've deployed 5 air quality sensors across Puerto Rico using Meshtastic mesh networking. They communicate via LoRa radio - no cellular or WiFi needed. Every 10 seconds, sensor data flows automatically to AWS cloud."

**Dashboard Walkthrough (2 minutes):**
1. Point to AQI gauges: "Real-time air quality index - all green means good air"
2. Show PM2.5 graph: "24-hour trend of particulate matter"
3. Show table: "Every pollutant we're measuring - PM2.5, PM10, VOC, NOx, temperature, humidity"
4. Change time range: "Can view hourly, daily, or weekly trends"

**Technical Highlights (1 minute):**
> "Data flows from sensor → mesh network → MQTT → AWS Timestream → Grafana dashboard. Total cost: about $3 per month for all 5 nodes. Scales easily to hundreds of nodes."

**Impact Statement (30 seconds):**
> "This enables real-time air quality monitoring for Puerto Rico communities, especially after events like wildfires or industrial incidents. Data is accessible 24/7 from any device."

---

## Cost Breakdown (Monthly)

| Service | Usage (5 nodes) | Cost |
|---------|-----------------|------|
| **Timestream Storage** | 150MB | $0.50 |
| **Timestream Queries** | ~100MB scanned | $0.50 |
| **EC2 t2.micro** | 730 hours/month | $0 (free tier) |
| **Data Transfer** | <1GB | $0.09 |
| **Grafana Cloud** | Free tier | $0 |
| **Total** | | **~$1-2/month** |

**Free tier benefits:**
- EC2: 750 hours/month free (1 year)
- Timestream: 1GB writes free, 1GB scans free (first 30 days)
- Grafana: Free forever tier

---

## Extensibility Plan

This demo extends easily to full production:

### Phase 2: Add Location Data
```bash
# Create DynamoDB table
aws dynamodb create-table \
  --table-name pulseaqi-locations \
  --attribute-definitions AttributeName=node_id,AttributeType=S \
  --key-schema AttributeName=node_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

### Phase 3: Add API Layer
```bash
# Create AppSync API
aws appsync create-graphql-api \
  --name pulseaqi-api \
  --authentication-type API_KEY
```

### Phase 4: Full Web App
```bash
# Deploy with Amplify
git init
amplify init
amplify add api
amplify push
```

---

## Troubleshooting

### No Data in Timestream
```bash
# Check EC2 service
ssh ubuntu@$PUBLIC_IP
sudo journalctl -u pulseaqi-mqtt -n 50

# Common issues:
# 1. IAM permissions - verify role has timestream:WriteRecords
# 2. MQTT topic mismatch - check logs for "Subscribed to topic"
# 3. Wrong region - ensure us-east-1 in all configs
```

### Grafana Shows No Data
```bash
# Test Timestream query manually
aws timestream-query query \
  --query-string "SELECT COUNT(*) FROM \"pulseaqi_demo\".\"sensor_data\"" \
  --region us-east-1

# Check data source permissions in Grafana
# Verify query syntax matches Timestream dialect
```

### High AWS Costs
```bash
# Check current spend
aws ce get-cost-and-usage \
  --time-period Start=$(date -d "-7 days" +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --metrics "UnblendedCost"

# Set billing alert
aws cloudwatch put-metric-alarm \
  --alarm-name pulseaqi-billing-alarm \
  --alarm-description "Alert when estimated charges exceed $10" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 21600 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold
```

---

## Cleanup (After Presentation)

```bash
# Stop EC2 (keep for later)
aws ec2 stop-instances --instance-ids $INSTANCE_ID

# Or terminate completely
aws ec2 terminate-instances --instance-ids $INSTANCE_ID

# Delete Timestream table (to stop charges)
aws timestream-write delete-table \
  --database-name pulseaqi_demo \
  --table-name sensor_data

# Delete database
aws timestream-write delete-database \
  --database-name pulseaqi_demo

# Delete security group
aws ec2 delete-security-group --group-id $SG_ID

# Delete IAM resources
aws iam remove-role-from-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile \
  --role-name pulseaqi-ec2-role

aws iam delete-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile

aws iam delete-role-policy \
  --role-name pulseaqi-ec2-role \
  --policy-name timestream-write-policy

aws iam delete-role --role-name pulseaqi-ec2-role
```

---

## Additional Resources

- **Meshtastic MQTT Documentation:** https://meshtastic.org/docs/software/mqtt/
- **AWS Timestream Docs:** https://docs.aws.amazon.com/timestream/
- **Grafana Timestream Plugin:** https://grafana.com/grafana/plugins/grafana-timestream-datasource/
- **EPA AQI Calculator:** https://www.airnow.gov/aqi/aqi-calculator/

---

## Repository Structure

```
pulseaqi-aws-demo/
├── README.md (this file)
├── mqtt_bridge.py
├── user-data.sh
├── ec2-trust-policy.json
├── timestream-write-policy.json
├── grafana-dashboard.json
├── setup.sh (automated setup script)
└── test/
    ├── test_mqtt_local.py
    └── test_timestream_query.py
```

---

## Quick Start Script

Save this as `setup.sh` for automated deployment:

```bash
#!/bin/bash
set -e

echo "🚀 PulseAQI AWS Demo Setup"
echo "================================"

# Load variables
source .env 2>/dev/null || true

# Prompt for missing variables
read -p "AWS Region [us-east-1]: " AWS_REGION
AWS_REGION=${AWS_REGION:-us-east-1}

read -p "EC2 Key Pair Name: " KEY_NAME
read -p "Your IP address (for SSH): " MY_IP

# Create Timestream resources
echo "📊 Creating Timestream database..."
aws timestream-write create-database --database-name pulseaqi_demo --region $AWS_REGION

echo "📊 Creating Timestream table..."
aws timestream-write create-table \
  --database-name pulseaqi_demo \
  --table-name sensor_data \
  --retention-properties "MemoryStoreRetentionPeriodInHours=24,MagneticStoreRetentionPeriodInDays=7" \
  --region $AWS_REGION

# Create IAM role
echo "🔐 Creating IAM role..."
aws iam create-role \
  --role-name pulseaqi-ec2-role \
  --assume-role-policy-document file://ec2-trust-policy.json

aws iam put-role-policy \
  --role-name pulseaqi-ec2-role \
  --policy-name timestream-write-policy \
  --policy-document file://timestream-write-policy.json

aws iam create-instance-profile --instance-profile-name pulseaqi-ec2-profile
aws iam add-role-to-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile \
  --role-name pulseaqi-ec2-role

sleep 10

# Create security group and EC2
echo "🖥️  Launching EC2 instance..."
SG_ID=$(aws ec2 create-security-group \
  --group-name pulseaqi-mqtt-bridge \
  --description "PulseAQI MQTT bridge" \
  --region $AWS_REGION \
  --query 'GroupId' \
  --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr ${MY_IP}/32

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --count 1 \
  --instance-type t2.micro \
  --key-name $KEY_NAME \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=pulseaqi-ec2-profile \
  --user-data file://user-data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=pulseaqi-mqtt-bridge}]' \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "⏳ Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo ""
echo "✅ Setup Complete!"
echo "================================"
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo ""
echo "Next steps:"
echo "1. SSH: ssh -i $KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo "2. Check logs: sudo journalctl -u pulseaqi-mqtt -f"
echo "3. Set up Grafana: https://grafana.com"
echo ""
echo "Dashboard will show data in ~2 minutes"
```

---

**Ready to deploy?** Just run:

```bash
chmod +x setup.sh
./setup.sh
```

Then configure Grafana and you're live! 🎉
