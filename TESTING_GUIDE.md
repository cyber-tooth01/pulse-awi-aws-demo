# Testing Guide - Meshtastic Protobuf Decoding

This guide shows you how to test the protobuf decoding implementation yourself, both locally and on EC2.

## Quick Start - Local Testing (No Hardware Required)

### 1. Install Dependencies

```bash
# Clone the repository
git clone https://github.com/cyber-tooth01/pulse-awi-aws-demo.git
cd pulse-awi-aws-demo

# Install Python dependencies
pip3 install -r requirements.txt
```

### 2. Run Unit Tests

Test protobuf encoding/decoding logic:

```bash
python3 test/test_protobuf_decode.py
```

**Expected output:**
```
============================================================
TEST 1: Node ID Extraction
============================================================
✓ Node ID 0xe70287b5 -> !e70287b5 (expected !e70287b5)
✓ Node ID 0x12345678 -> !12345678 (expected !12345678)
✓ Node ID 0x00000000 -> !00000000 (expected !00000000)
✓ Node ID 0xffffffff -> !ffffffff (expected !ffffffff)

...

============================================================
All tests completed successfully!
============================================================
```

### 3. Run Integration Tests

Test the full MQTT bridge message processing:

```bash
python3 test/test_mqtt_bridge_integration.py
```

**Expected output:**
```
============================================================
Integration Test: Protobuf Message Parsing
============================================================
✓ Created protobuf message: 111 bytes
✓ Parsed ServiceEnvelope
✓ Extracted node ID: !e70287b5
✓ Has decoded field: True
✓ Port number: 1
✓ Decoded text payload (93 chars)
✓ Parsed sensor JSON: 8 fields
✓ All required fields present: ['pm1', 'pm25', 'pm4', 'pm10', 'voc', 'nox', 't', 'rh']
✓ PM2.5 value: 4.5 µg/m³

✓ Integration test PASSED
```

### 4. Generate Test Messages

Create sample protobuf messages to understand the format:

```bash
# Generate default test message
python3 test/protobuf_message_generator.py

# Generate with custom values
python3 test/protobuf_message_generator.py --pm25 15.3 --temp 28.5 --hex

# See all options
python3 test/protobuf_message_generator.py --help
```

**Example output:**
```
============================================================
Protobuf Message Details
============================================================
Node ID:      !e70287b5
Channel:      pulse-aqi
Gateway:      !gatewaynode
Port:         1 (TEXT_MESSAGE_APP)
Payload:      {"pm1": 3, "pm25": 4.5, "pm4": 5, "pm10": 5.0, "voc": 103.0, "nox": 1.0, "t": 24.7, "rh": 63.8}

Sensor Data:
  PM2.5:      4.5 µg/m³
  PM10:       5.0 µg/m³
  VOC:        103.0
  NOx:        1.0
  Temp:       24.7°C
  Humidity:   63.8%

Serialized Size: 138 bytes
```

## Testing with Live MQTT (Requires Meshtastic Nodes)

### 5. Monitor Live MQTT Messages

Connect to the public Meshtastic MQTT broker to see real messages:

```bash
python3 test/test_mqtt_local.py
```

This will connect to `mqtt.meshtastic.org` and display all messages on the `pulse-aqi` channel.

**What you'll see:**

For **protobuf messages** (what we're decoding):
```
📬 Message from msh/US/2/e/pulse-aqi/!e70287b5
   Payload length: 138 bytes
   Format: Binary Protobuf
   ✓ Parsed protobuf ServiceEnvelope (138 bytes)
   Sender: !e70287b5
   Port: 1 (expecting 1)
   Decoded port 1 text from !e70287b5: {"pm1":3,"pm25":4.5,...}
   ✓ Parsed sensor JSON from protobuf (node !e70287b5)
   📊 Sensor Data:
      PM2.5: 4.5 µg/m³
      PM10:  5.0 µg/m³
      VOC:   103.0
      NOx:   1.0
      Temp:  24.7°C
      RH:    63.8%
```

For **JSON messages** (legacy format):
```
📬 Message from msh/US/2/e/pulse-aqi/!12345678
   Payload length: 245 bytes
   Format: JSON
   Type: text
   Sender: !12345678
   📊 Sensor Data:
      PM2.5: 5.2 µg/m³
      ...
```

**Note:** If you don't have Meshtastic nodes sending data, you won't see messages. The script will just wait and show "Listening for messages..."

## Testing on EC2 (Production Environment)

### 6. Deploy and Test on EC2

#### A. Upload Files to EC2

```bash
# Set your EC2 details
EC2_IP="YOUR_EC2_PUBLIC_IP"
KEY_FILE="your-key.pem"

# Upload updated bridge and dependencies
scp -i $KEY_FILE mqtt_bridge.py ubuntu@$EC2_IP:/opt/pulseaqi/
scp -i $KEY_FILE requirements.txt ubuntu@$EC2_IP:/opt/pulseaqi/
```

#### B. Install Dependencies on EC2

```bash
# SSH to EC2
ssh -i $KEY_FILE ubuntu@$EC2_IP

# Install/update Python packages
sudo pip3 install -r /opt/pulseaqi/requirements.txt

# Verify meshtastic package installed
python3 -c "from meshtastic.protobuf import mqtt_pb2, portnums_pb2; print('✓ Protobuf support ready')"
```

#### C. Set Environment Variables

Make sure InfluxDB credentials are set:

```bash
# Edit the systemd service file
sudo nano /etc/systemd/system/pulseaqi-mqtt.service
```

Ensure these environment variables are present:
```ini
Environment="INFLUXDB_TOKEN=your_token_here"
Environment="INFLUXDB_ORG=your_org_here"
Environment="INFLUXDB_BUCKET=pulseaqi"
Environment="INFLUXDB_URL=https://us-east-1-1.aws.cloud2.influxdata.com"
```

#### D. Restart Service

```bash
sudo systemctl daemon-reload
sudo systemctl restart pulseaqi-mqtt
```

#### E. Monitor Logs

Watch the service logs in real-time:

```bash
sudo journalctl -u pulseaqi-mqtt -f
```

**Success indicators to look for:**

```
✓ Connected to MQTT broker: mqtt.meshtastic.org
✓ Subscribed to topic: msh/US/2/e/pulse-aqi/#
✓ Parsed protobuf ServiceEnvelope (138 bytes)
Protobuf message from !e70287b5, port=1 (expecting 1)
Decoded port 1 text from !e70287b5: {"pm1":3,"pm25":4.5,...}
✓ Parsed sensor JSON from protobuf (node !e70287b5)
📊 Node !e70287b5: AQI=18 (Good), PM2.5=4.5 µg/m³
✓ Wrote sensor data to InfluxDB
```

**Error messages (and how to fix them):**

| Error | Meaning | Fix |
|-------|---------|-----|
| `meshtastic package not installed` | Missing dependency | `sudo pip3 install meshtastic>=2.2.0` |
| `Skipping encrypted message` | Node has encryption ON | Run `meshtastic --ch-set psk base64:Sw==` on node |
| `Skipping port X` | Wrong message type | Ensure sensor sends on port 1 (TEXT_MESSAGE_APP) |
| `UTF-8 decode error` | Corrupted transmission | Check LoRa signal strength |
| `Missing required fields` | Incomplete sensor data | Verify sensor JSON format |

### 7. Verify Data in InfluxDB

Check that data is being written:

```bash
# Using InfluxDB CLI (if you have it)
influx query 'from(bucket:"pulseaqi") 
  |> range(start: -1h) 
  |> filter(fn: (r) => r._measurement == "air_quality")'

# Or check in InfluxDB Web UI:
# 1. Go to Data Explorer
# 2. Select bucket: pulseaqi
# 3. Select measurement: air_quality
# 4. Should see recent data points
```

## Troubleshooting

### "No messages appearing"

1. **Check MQTT connection:**
   ```bash
   # Test with mosquitto_sub (if installed)
   mosquitto_sub -h mqtt.meshtastic.org -t "msh/US/2/e/pulse-aqi/#" -v
   ```

2. **Verify Meshtastic node is transmitting:**
   - Check node display shows MQTT enabled
   - Verify channel name is "pulse-aqi"
   - Confirm node has LoRa connectivity

3. **Check topic match:**
   - MQTT topic in code: `msh/US/2/e/pulse-aqi/#`
   - Verify your channel publishes to this topic

### "Protobuf decode errors"

1. **Check Python version:**
   ```bash
   python3 --version  # Should be 3.8+
   ```

2. **Verify package versions:**
   ```bash
   pip3 show meshtastic
   # Should be >= 2.2.0
   ```

3. **Test protobuf import:**
   ```bash
   python3 -c "from meshtastic.protobuf import mqtt_pb2; print('OK')"
   ```

### "InfluxDB write errors"

1. **Verify credentials:**
   ```bash
   echo $INFLUXDB_TOKEN  # Should not be empty
   echo $INFLUXDB_ORG    # Should not be empty
   ```

2. **Test InfluxDB connection:**
   ```bash
   curl -I $INFLUXDB_URL/health
   # Should return: HTTP/2 200
   ```

## Visual Verification

After everything is running, you should see:

1. **In logs:** Regular messages showing protobuf decode → AQI calculation → InfluxDB write
2. **In InfluxDB:** New data points every 30-60 seconds (depending on sensor send interval)
3. **In Grafana:** Dashboard showing live PM2.5, AQI, temperature, humidity graphs

## Quick Test Checklist

Use this checklist to verify everything works:

- [ ] Unit tests pass: `python3 test/test_protobuf_decode.py`
- [ ] Integration tests pass: `python3 test/test_mqtt_bridge_integration.py`
- [ ] Can generate test messages: `python3 test/protobuf_message_generator.py`
- [ ] Can monitor live MQTT: `python3 test/test_mqtt_local.py` (if nodes available)
- [ ] EC2 service running: `systemctl status pulseaqi-mqtt`
- [ ] Logs show protobuf decoding: `journalctl -u pulseaqi-mqtt | grep "Parsed protobuf"`
- [ ] Data in InfluxDB: Check Data Explorer
- [ ] Grafana dashboard updating: Check live view

## Next Steps

Once testing is complete:

1. **Monitor for 24 hours** to ensure stability
2. **Check InfluxDB costs** - should be minimal on free tier
3. **Add more nodes** - each gets unique node ID (!xxxxxxxx)
4. **Customize dashboards** - add panels for VOC, NOx, etc.

## Support Resources

- **PROTOBUF_GUIDE.md** - Deep dive into protobuf message structure
- **DEPLOYMENT_GUIDE.md** - Production deployment steps
- **IMPLEMENTATION_SUMMARY.md** - Technical architecture details
- **GitHub Issues** - Report bugs or ask questions

---

**Questions?** Check the guides above or open a GitHub issue!
