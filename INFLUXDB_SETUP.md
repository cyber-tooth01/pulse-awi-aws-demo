# InfluxDB Serverless Setup for PulseAQI

## 1. Create InfluxDB Cloud Account

1. Go to https://cloud2.influxdata.com/
2. Sign up for free account (serverless tier)
3. Choose region: **us-east-1** (or closest to your EC2)

## 2. Create Bucket

1. In InfluxDB UI: **Load Data** → **Buckets** → **Create Bucket**
2. Name: `pulseaqi`
3. Retention: 7 days (or longer if desired)

## 3. Generate API Token

1. **Load Data** → **API Tokens** → **Generate API Token**
2. Select **Custom API Token**
3. Permissions:
   - Bucket: `pulseaqi` → **Write** (required)
   - Bucket: `pulseaqi` → **Read** (for Grafana queries)
4. Description: `pulseaqi-bridge`
5. Copy token (save securely; won't be shown again)

## 4. Get Organization Name

1. Click user icon (top right) → **About**
2. Copy **Organization** value (or **Organization ID**)

## 5. Configure Local Environment

```bash
# Copy example env file
cp .env.influx.example .env

# Edit .env with your values
nano .env
```

Set:
```bash
INFLUXDB_TOKEN=your_actual_token_from_step3
INFLUXDB_ORG=your_org_name_from_step4
INFLUXDB_BUCKET=pulseaqi
INFLUXDB_URL=https://us-east-1-1.aws.cloud2.influxdata.com
```

## 6. Test Locally

```bash
source .venv/bin/activate
export $(cat .env | xargs)
python mqtt_bridge.py
```

## 7. Deploy to EC2

### Update systemd service with credentials:
```bash
ssh -i pulseaqi-demo-key.pem ubuntu@54.89.169.167

# Edit service file
sudo nano /etc/systemd/system/pulseaqi-mqtt.service
```

Replace placeholder values in `Environment=` lines:
```ini
Environment="INFLUXDB_TOKEN=your_actual_token"
Environment="INFLUXDB_ORG=your_org_name"
Environment="INFLUXDB_BUCKET=pulseaqi"
Environment="INFLUXDB_URL=https://us-east-1-1.aws.cloud2.influxdata.com"
```

### Upload updated bridge and restart:
```bash
# From local machine
scp -i pulseaqi-demo-key.pem mqtt_bridge.py ubuntu@54.89.169.167:/opt/pulseaqi/
scp -i pulseaqi-demo-key.pem requirements.txt ubuntu@54.89.169.167:/opt/pulseaqi/

# On EC2
ssh -i pulseaqi-demo-key.pem ubuntu@54.89.169.167
sudo pip3 install -r /opt/pulseaqi/requirements.txt
# This installs: influxdb-client, meshtastic (for protobuf decoding), paho-mqtt
sudo systemctl daemon-reload
sudo systemctl restart pulseaqi-mqtt
sudo journalctl -u pulseaqi-mqtt -f
```

## 8. Verify Data Ingestion

In InfluxDB UI:
1. **Data Explorer**
2. Select bucket: `pulseaqi`
3. Measurement: `air_quality`
4. Fields: `pm25`, `aqi`, `temperature`, etc.
5. Tag: `node_id`
6. Submit → should see data points

## 9. Grafana Setup (InfluxDB Data Source)

1. Grafana → **Connections** → **Add data source** → **InfluxDB**
2. Settings:
   - **Query Language**: Flux
   - **URL**: `https://us-east-1-1.aws.cloud2.influxdata.com`
   - **Organization**: Your org name from step 4
   - **Token**: Same token from step 3
   - **Default Bucket**: `pulseaqi`
3. **Save & Test**

### Example Flux Query for PM2.5:
```flux
from(bucket: "pulseaqi")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "air_quality")
  |> filter(fn: (r) => r["_field"] == "pm25")
  |> filter(fn: (r) => r["node_id"] == "!e70287b5")
```

## 10. Cost Estimate

InfluxDB Serverless free tier:
- Write: 5 MB/month free, then $0.002/MB
- Query: 300 MB/month free, then $0.002/MB
- Storage: Free up to 30-day retention

Typical usage (1 node, 60s interval):
- ~1 point/min × 1440 min/day × 7 days = 10,080 points
- ~300 bytes/point = ~3 MB/week
- **Free tier sufficient for 5-10 nodes**
