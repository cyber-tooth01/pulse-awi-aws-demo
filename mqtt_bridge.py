#!/usr/bin/env python3
"""
PulseAQI MQTT to InfluxDB Bridge
Subscribes to Meshtastic MQTT, parses sensor data, writes to InfluxDB Serverless
"""

import json
import paho.mqtt.client as mqtt
from datetime import datetime
import logging
import sys
import time
import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# Setup logging first (before any usage)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/pulseaqi-mqtt.log')
    ]
)
logger = logging.getLogger(__name__)

# Try importing Meshtastic protobuf support (optional)
try:
    from meshtastic.protobuf import mqtt_pb2, portnums_pb2
    PROTOBUF_AVAILABLE = True
except ImportError:
    logger.warning("meshtastic package not installed - protobuf decoding disabled")
    PROTOBUF_AVAILABLE = False

# Configuration
MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_TOPIC = "msh/US/2/e/pulse-aqi/#"
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"

# InfluxDB Configuration (set via environment variables)
INFLUXDB_URL = os.environ.get('INFLUXDB_URL', 'https://us-east-1-1.aws.cloud2.influxdata.com')
INFLUXDB_TOKEN = os.environ.get('INFLUXDB_TOKEN')  # Required
INFLUXDB_ORG = os.environ.get('INFLUXDB_ORG')  # Required
INFLUXDB_BUCKET = os.environ.get('INFLUXDB_BUCKET', 'pulseaqi')

if not INFLUXDB_TOKEN or not INFLUXDB_ORG:
    logger.error("INFLUXDB_TOKEN and INFLUXDB_ORG environment variables must be set")
    sys.exit(1)

# Initialize InfluxDB client
influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

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

def make_influx_point(node_id, timestamp_ms, sensor_data, aqi, category):
    """Create an InfluxDB Point with all sensor metrics"""
    point = Point("air_quality") \
        .tag("node_id", node_id) \
        .tag("aqi_category", category) \
        .field("pm1", float(sensor_data['pm1'])) \
        .field("pm25", float(sensor_data['pm25'])) \
        .field("pm4", float(sensor_data['pm4'])) \
        .field("pm10", float(sensor_data['pm10'])) \
        .field("voc", float(sensor_data['voc'])) \
        .field("nox", float(sensor_data['nox'])) \
        .field("temperature", float(sensor_data['t'])) \
        .field("humidity", float(sensor_data['rh'])) \
        .field("aqi", aqi) \
        .time(timestamp_ms * 1_000_000)  # Convert ms to nanoseconds
    return point

def write_to_influxdb(point):
    """Write point to InfluxDB with retry logic"""
    try:
        write_api.write(bucket=INFLUXDB_BUCKET, record=point)
        logger.info(f"✓ Wrote sensor data to InfluxDB")
        return True
    except Exception as e:
        logger.error(f"Error writing to InfluxDB: {e}")
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

def _get_node_id_from_packet(packet):
    """Return Meshtastic node id string from a protobuf packet, handling field name variants."""
    fid = None
    try:
        # Some protobuf builds expose 'from_' while others use 'from'
        if hasattr(packet, 'from_') and packet.from_:
            fid = packet.from_
        elif hasattr(packet, 'from') and getattr(packet, 'from'):
            fid = getattr(packet, 'from')
    except Exception:
        fid = None
    return f"!{fid:08x}" if fid else None


def _decrypt_payload(encrypted_bytes, psk):
    """
    Decrypt Meshtastic encrypted payload using AES-128-CTR with PSK as key.
    Returns decrypted bytes or None on failure.
    """
    try:
        # Meshtastic uses first 4 bytes as nonce, rest as ciphertext
        if len(encrypted_bytes) < 4:
            logger.debug("Encrypted payload too short")
            return None
        
        nonce = encrypted_bytes[:4]
        ciphertext = encrypted_bytes[4:]
        
        # Construct 16-byte IV: nonce (4 bytes) + zeros (12 bytes)
        iv = nonce + b'\x00' * 12
        
        # Pad PSK to 16 bytes if needed
        key = psk if len(psk) >= 16 else psk + b'\x00' * (16 - len(psk))
        
        cipher = AES.new(key[:16], AES.MODE_CTR, nonce=iv[:12])
        plaintext = cipher.decrypt(ciphertext)
        
        logger.debug(f"Decrypted {len(ciphertext)} bytes → {len(plaintext)} bytes")
        return plaintext
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None


def on_message(client, userdata, msg):
    """MQTT message callback - main processing logic"""
    try:
        node_id = None
        sensor_data = None
        
        # Try JSON format first
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            logger.debug(f"Received JSON from {msg.topic}")
            
            if payload.get('type') != 'text':
                logger.debug(f"Skipping non-text message type: {payload.get('type')}")
                return
            
            node_id = payload.get('sender', 'unknown')
            sensor_text = payload.get('payload', {}).get('text', '')
            
            if sensor_text.startswith('{'):
                sensor_data = json.loads(sensor_text)
                
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Try protobuf format
            if not PROTOBUF_AVAILABLE:
                logger.debug("Binary message received but protobuf support not available")
                return
            
            try:
                envelope = mqtt_pb2.ServiceEnvelope()
                envelope.ParseFromString(msg.payload)

                node_id = _get_node_id_from_packet(envelope.packet)

                port = getattr(envelope.packet.decoded, 'portnum', 0)
                
                # Only process port 1 (TEXT_MESSAGE_APP) - our sensor data
                if port != 1:
                    logger.debug(f"Skipping non-sensor message; port={port}")
                    return
                
                # Port 1 messages should be plaintext JSON (MQTT encryption disabled)
                payload_bytes = envelope.packet.decoded.payload
                text_payload = None
                
                try:
                    text_payload = payload_bytes.decode('utf-8', errors='ignore')
                except Exception:
                    logger.debug(f"Could not decode port 1 payload as UTF-8")
                    return

                if text_payload and text_payload.strip().startswith('{'):
                    logger.debug(f"Decoded protobuf text from {node_id}: {text_payload[:100]}")
                    sensor_data = json.loads(text_payload)
                else:
                    logger.debug(f"Port 1 payload is not JSON")
                    return

            except Exception as e:
                logger.error(f"Protobuf decode error: {e}")
                return
        
        # Validate we got the data we need
        if not node_id or not sensor_data:
            logger.debug("Could not extract node_id or sensor_data")
            return
        
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
        
        # Prepare InfluxDB point
        timestamp_ms = int(datetime.utcnow().timestamp() * 1000)
        point = make_influx_point(node_id, timestamp_ms, sensor_data, aqi, category)
        
        # Write to InfluxDB
        write_to_influxdb(point)
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)

def main():
    """Main application loop"""
    logger.info("=" * 60)
    logger.info("PulseAQI MQTT to InfluxDB Bridge Starting")
    logger.info(f"MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"MQTT Topic: {MQTT_TOPIC}")
    logger.info(f"InfluxDB Bucket: {INFLUXDB_BUCKET}")
    logger.info(f"InfluxDB Org: {INFLUXDB_ORG}")
    logger.info("=" * 60)
    
    # Create MQTT client
    client = mqtt.Client(client_id="pulseaqi-bridge")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    
    # Set authentication credentials
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
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
