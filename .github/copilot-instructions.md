# PulseAQI AWS Demo - AI Agent Instructions

## Project Overview
Demonstration infrastructure for Meshtastic-based air quality monitoring using AWS cloud services. This is a **setup guide project**, not an active codebase - all implementation code is embedded as examples within the main markdown document.

## Architecture Understanding

**Data Flow Pipeline:**
```
Meshtastic Mesh (LoRa) → MQTT Bridge Node → mqtt.meshtastic.org 
  → EC2 MQTT Bridge (Python) → AWS Timestream → Grafana Cloud Dashboard
```

**MQTT Topic Structure:** `msh/US/2/e/pulse-aqi/#`
- Meshtastic publishes JSON messages with nested sensor data
- Payload format: `{"sender": "!e70287b5", "type": "text", "payload": {"text": "{JSON sensor data}"}}`

**AWS Components:**
- **Timestream:** Time-series database with 24-hour memory retention, 7-day magnetic storage
- **EC2 t2.micro:** Runs Python MQTT bridge with systemd service
- **IAM Role:** `pulseaqi-ec2-role` with `timestream:WriteRecords` permission

## Key Files & Structure

This workspace contains only documentation:
- [`# PulseAQI AWS Demo Setup Guide.md`](# PulseAQI AWS Demo Setup Guide.md) - Complete setup guide with embedded code

**Expected files (not yet created):**
- `mqtt_bridge.py` - MQTT→Timestream bridge (Python 3, paho-mqtt, boto3)
- `user-data.sh` - EC2 bootstrap script for systemd service setup
- `setup.sh` - Automated AWS deployment script
- `ec2-trust-policy.json`, `timestream-write-policy.json` - IAM configurations

## Critical Implementation Patterns

### Sensor Data Processing
1. **Message Validation:** Only process `type: "text"` messages with JSON payloads
2. **Required Sensor Fields:** pm1, pm25, pm4, pm10, voc, nox, t (temp), rh (humidity)
3. **AQI Calculation:** Uses EPA breakpoints for PM2.5 (see `calculate_aqi_pm25()` function)
4. **Timestream Record Format:**
   ```python
   {
       'Dimensions': [{'Name': 'node_id', 'Value': sender_id},
                      {'Name': 'metric', 'Value': 'pm25'}],
       'MeasureName': 'value',
       'MeasureValue': str(value),
       'MeasureValueType': 'DOUBLE',
       'Time': str(int(timestamp_ms))
   }
   ```

### AWS Configuration Defaults
- **Region:** `us-east-1` (hardcoded throughout)
- **Database:** `pulseaqi_demo`
- **Table:** `sensor_data`
- **EC2 Instance Type:** `t2.micro` (free tier eligible)
- **MQTT Broker:** `mqtt.meshtastic.org:1883` (public, no auth)

### Service Management
- **Systemd service:** `pulseaqi-mqtt.service`
- **Working directory:** `/opt/pulseaqi`
- **Log location:** `/var/log/pulseaqi-mqtt.log`
- **Restart policy:** Always with 10s delay

## Common Development Tasks

### Adding New Sensor Metrics
When adding new sensor fields (e.g., CO2, noise level):
1. Update `required_fields` list in `on_message()` validation
2. Add new `make_timestream_record()` call in records array
3. Update Grafana dashboard JSON with new panel/query
4. Document units in AQI calculation docstrings

### Modifying MQTT Topic
Change `MQTT_TOPIC` constant, but maintain wildcard pattern `msh/US/2/e/pulse-aqi/#` for multi-node support.

### Timestream Query Patterns
Use SQL-like syntax with time-series functions:
```sql
SELECT node_id, measure_value::double as pm25 
FROM "pulseaqi_demo"."sensor_data" 
WHERE measure_name = 'value' AND dimension_metric = 'pm25' 
  AND time > ago(24h) 
ORDER BY time DESC
```

## Testing & Debugging

**Local MQTT Testing:**
```bash
mosquitto_sub -h mqtt.meshtastic.org -t "msh/US/2/e/pulse-aqi/#" -v
```

**EC2 Service Debugging:**
```bash
sudo journalctl -u pulseaqi-mqtt -f --since "10 minutes ago"
sudo systemctl status pulseaqi-mqtt
```

**Timestream Query Verification:**
```bash
aws timestream-query query --query-string "SELECT COUNT(*) FROM \"pulseaqi_demo\".\"sensor_data\"" --region us-east-1
```

## Cost Optimization
- **Target monthly cost:** $1-3 for 5 nodes
- **Free tier dependencies:** EC2 (750 hrs/month first year), Grafana Cloud (free forever tier)
- **Billable components:** Timestream storage ($0.50/GB), query scans ($0.01/GB), data transfer

## Constraints & Assumptions

- **No authentication:** Public MQTT broker, open Grafana (presentation demo)
- **Data retention:** 7 days max (to minimize costs)
- **Region locked:** us-east-1 (must update 8+ places to change)
- **Single EC2 instance:** No high availability/redundancy
- **Python dependencies:** Requires manual pip install (paho-mqtt, boto3)

## What NOT to Change

- AQI calculation breakpoints (EPA standard)
- Timestream dimension schema (node_id, metric) - breaking change for queries
- MQTT payload format (Meshtastic protocol dependency)
- IAM role trust policy (EC2-specific)

## Extension Points (Phase 2+)

Documented in guide but not implemented:
- DynamoDB table for node location metadata
- AppSync GraphQL API layer
- AWS Amplify web application
- CloudWatch billing alarms
