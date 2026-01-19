# PulseAQI AWS Demo

**Real-time air quality monitoring using Meshtastic mesh networks and AWS cloud services**

![Architecture](https://img.shields.io/badge/Architecture-IoT%20%2B%20AWS-blue)
![Cost](https://img.shields.io/badge/Monthly%20Cost-%241--3-green)
![Setup Time](https://img.shields.io/badge/Setup%20Time-4--6%20hours-orange)

## Quick Overview

This project demonstrates a low-cost, scalable air quality monitoring system:
- **Sensors**: Meshtastic LoRa mesh network nodes
- **Data Pipeline**: MQTT → AWS Timestream → Grafana Cloud
- **Cost**: ~$1-3/month for 5 nodes (AWS free tier eligible)
- **Use Case**: Real-time air quality monitoring for Puerto Rico communities

## Architecture

```
Meshtastic Mesh (LoRa) → MQTT Bridge → mqtt.meshtastic.org
    → EC2 MQTT Bridge (Python) → AWS Timestream → Grafana Dashboard
```

## Prerequisites

1. **AWS Account** with free tier access
2. **AWS CLI** configured with credentials
3. **Python 3.8+** with pip
4. **EC2 Key Pair** created in your AWS region
5. **Meshtastic nodes** configured to publish to MQTT

## Quick Start

### 1. Clone and Configure

```bash
# Clone repository
git clone <your-repo-url>
cd pulse-awi-aws-demo

# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env
```

### 2. Install Dependencies (Local Testing)

```bash
pip install paho-mqtt boto3
```

### 3. Test MQTT Connection

```bash
# Verify your sensors are publishing data
python test/test_mqtt_local.py
```

### 4. Deploy to AWS

**Option A: Automated Setup**
```bash
chmod +x setup.sh
./setup.sh
```

**Option B: Manual Setup**

Follow the detailed guide in [`# PulseAQI AWS Demo Setup Guide.md`](# PulseAQI AWS Demo Setup Guide.md)

### 5. Upload Bridge Script

```bash
# After EC2 instance is running
scp -i your-key.pem mqtt_bridge.py ubuntu@<PUBLIC_IP>:/opt/pulseaqi/
```

### 6. Start Service

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@<PUBLIC_IP>

# Start the bridge service
sudo systemctl start pulseaqi-mqtt

# Check status
sudo systemctl status pulseaqi-mqtt

# View logs
sudo journalctl -u pulseaqi-mqtt -f
```

### 7. Configure Grafana

1. Sign up at [grafana.com](https://grafana.com) (free tier)
2. Add AWS Timestream data source
3. Import dashboard from `grafana-dashboard.json`

## Project Structure

```
pulse-awi-aws-demo/
├── mqtt_bridge.py              # Main MQTT→Timestream bridge
├── setup.sh                    # Automated AWS deployment script
├── user-data.sh                # EC2 bootstrap script
├── ec2-trust-policy.json       # IAM role trust policy
├── timestream-write-policy.json # IAM permissions policy
├── grafana-dashboard.json      # Grafana dashboard config
├── .env.example                # Environment variables template
├── .gitignore                  # Git ignore rules
├── test/
│   ├── test_mqtt_local.py      # Local MQTT testing
│   └── test_timestream_query.py # Timestream query testing
├── .github/
│   └── copilot-instructions.md # AI agent guidance
└── # PulseAQI AWS Demo Setup Guide.md  # Detailed setup guide
```

## Key Features

- **EPA-Standard AQI Calculation**: Accurate PM2.5-based Air Quality Index
- **Multi-Node Support**: Monitor multiple sensors simultaneously
- **Real-time Updates**: 10-second refresh in Grafana
- **Cost Optimized**: 7-day data retention, minimal query overhead
- **Auto-Recovery**: Systemd service with automatic restart
- **Comprehensive Logging**: CloudWatch and local logs for debugging

## Sensor Data Format

Expected MQTT payload structure:
```json
{
  "sender": "!e70287b5",
  "type": "text",
  "payload": {
    "text": "{\"pm1\":3,\"pm25\":4,\"pm4\":5,\"pm10\":5,\"voc\":103.0,\"nox\":1.0,\"t\":24.7,\"rh\":63.8}"
  }
}
```

## Testing & Verification

### Test MQTT Connection
```bash
python test/test_mqtt_local.py
```

### Test Timestream Queries
```bash
python test/test_timestream_query.py
```

### Query Timestream via AWS CLI
```bash
aws timestream-query query \
  --query-string "SELECT * FROM \"pulseaqi_demo\".\"sensor_data\" LIMIT 10" \
  --region us-east-1
```

## Cost Breakdown

| Service | Usage (5 nodes) | Monthly Cost |
|---------|-----------------|--------------|
| Timestream Storage | ~150MB | $0.50 |
| Timestream Queries | ~100MB scanned | $0.50 |
| EC2 t2.micro | 730 hrs | **$0** (free tier) |
| Data Transfer | <1GB | $0.09 |
| **Total** | | **~$1-2/month** |

## Troubleshooting

### No Data in Timestream
```bash
# Check EC2 service status
ssh ubuntu@<PUBLIC_IP>
sudo journalctl -u pulseaqi-mqtt -n 50

# Common issues:
# - IAM permissions missing
# - Wrong MQTT topic
# - Region mismatch
```

### Grafana Shows No Data
- Verify Timestream data exists: `python test/test_timestream_query.py`
- Check Grafana data source credentials
- Ensure queries use correct database/table names

### High AWS Costs
```bash
# Check current spend
aws ce get-cost-and-usage \
  --time-period Start=$(date -d "-7 days" +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --metrics "UnblendedCost"
```

## Extending the Project

### Add New Sensor Metrics
1. Update `required_fields` in `mqtt_bridge.py`
2. Add new `make_timestream_record()` call
3. Update Grafana dashboard with new panel

### Support Multiple MQTT Topics
Modify `MQTT_TOPIC` to use wildcards: `msh/+/+/e/pulse-aqi/#`

### Add Location Metadata
Create DynamoDB table to store node locations and link to sensor data

## Cleanup

```bash
# Stop EC2 instance (keeps data)
aws ec2 stop-instances --instance-ids <INSTANCE_ID>

# Or terminate completely
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>

# Delete Timestream resources
aws timestream-write delete-table --database-name pulseaqi_demo --table-name sensor_data
aws timestream-write delete-database --database-name pulseaqi_demo

# Remove IAM resources
aws iam remove-role-from-instance-profile --instance-profile-name pulseaqi-ec2-profile --role-name pulseaqi-ec2-role
aws iam delete-instance-profile --instance-profile-name pulseaqi-ec2-profile
aws iam delete-role-policy --role-name pulseaqi-ec2-role --policy-name timestream-write-policy
aws iam delete-role --role-name pulseaqi-ec2-role
```

## Resources

- **Meshtastic MQTT**: https://meshtastic.org/docs/software/mqtt/
- **AWS Timestream**: https://docs.aws.amazon.com/timestream/
- **Grafana Timestream Plugin**: https://grafana.com/grafana/plugins/grafana-timestream-datasource/
- **EPA AQI Reference**: https://www.airnow.gov/aqi/aqi-calculator/

## Contributing

This is a demonstration project. Feel free to fork and adapt for your needs!

## License

MIT License - See LICENSE file for details

---

**Ready to deploy?** Start with `./setup.sh` or follow the detailed guide!
