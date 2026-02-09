# Quick Deployment Guide

## Prerequisites
- EC2 instance running with mqtt_bridge.py service
- InfluxDB credentials configured
- Meshtastic nodes configured with encryption OFF

## Deployment Steps

### 1. Install Dependencies on EC2
```bash
ssh -i your-key.pem ubuntu@YOUR_EC2_IP

# Install Python packages
sudo pip3 install -r /opt/pulseaqi/requirements.txt

# Verify meshtastic package
python3 -c "from meshtastic.protobuf import mqtt_pb2; print('✓ OK')"
```

### 2. Upload Updated Files
```bash
# From your local machine
scp -i your-key.pem mqtt_bridge.py ubuntu@YOUR_EC2_IP:/opt/pulseaqi/
scp -i your-key.pem requirements.txt ubuntu@YOUR_EC2_IP:/opt/pulseaqi/
```

### 3. Restart Service
```bash
# On EC2
sudo systemctl daemon-reload
sudo systemctl restart pulseaqi-mqtt
```

### 4. Monitor Logs
```bash
# Watch for protobuf decoding messages
sudo journalctl -u pulseaqi-mqtt -f

# Look for these success indicators:
# ✓ Parsed protobuf ServiceEnvelope
# ✓ Parsed sensor JSON from protobuf (node !xxxxxxxx)
# ✓ Wrote sensor data to InfluxDB
```

## Testing Before Deployment

### Local MQTT Monitoring
```bash
python3 test/test_mqtt_local.py
```
Look for messages like:
```
📬 Message from msh/US/2/e/pulse-aqi/!xxxxxxxx
   Format: Binary Protobuf
   Sender: !e70287b5
   Port: 1
   Decoded port 1 text from !e70287b5: {"pm25": 4.5, ...}
   📊 Sensor Data:
      PM2.5: 4.5 µg/m³
```

### Unit Tests
```bash
python3 test/test_protobuf_decode.py
python3 test/test_mqtt_bridge_integration.py
```
Both should show: **All tests completed successfully!**

## Verification Checklist

After deployment:

- [ ] Service running: `systemctl status pulseaqi-mqtt`
- [ ] No errors in logs: `journalctl -u pulseaqi-mqtt -n 50`
- [ ] Protobuf messages being decoded (see "Parsed protobuf" in logs)
- [ ] Data appearing in InfluxDB
- [ ] AQI calculations working
- [ ] Multiple nodes being tracked

## Troubleshooting

### "meshtastic package not installed"
```bash
sudo pip3 install meshtastic>=2.2.0
sudo systemctl restart pulseaqi-mqtt
```

### "Skipping encrypted message"
Your Meshtastic node still has encryption enabled. Fix:
```bash
meshtastic --ch-set psk base64:Sw== --ch-index 0
```

### "Port X is not TEXT_MESSAGE_APP"
Node is sending wrong message type. Ensure sensor data is sent on port 1 (TEXT_MESSAGE_APP).

### "UTF-8 decode error"
Possible mesh transmission corruption. Check:
- Signal strength (RSSI/SNR)
- Node firmware version
- Message format on sending node

## Quick Reference

| Item | Value |
|------|-------|
| MQTT Broker | mqtt.meshtastic.org:1883 |
| MQTT Topic | msh/US/2/e/pulse-aqi/# |
| Port Number | 1 (TEXT_MESSAGE_APP) |
| Service Name | pulseaqi-mqtt |
| Log Location | /var/log/pulseaqi-mqtt.log |
| Config Location | /opt/pulseaqi/ |

## Support

- See `PROTOBUF_GUIDE.md` for detailed technical info
- See `IMPLEMENTATION_SUMMARY.md` for architecture details
- See `README.md` for general project info

---
**Last Updated**: 2024
**Status**: Production Ready ✓
