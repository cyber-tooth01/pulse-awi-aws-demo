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
    from meshtastic.protobuf import mqtt_pb2, portnums_pb2, telemetry_pb2
    PROTOBUF_AVAILABLE = True
except ImportError:
    logger.warning("meshtastic package not installed - protobuf decoding disabled")
    PROTOBUF_AVAILABLE = False

# Port numbers for supported message types
TEXT_MESSAGE_APP_PORT = 1
TELEMETRY_APP_PORT = 67
TEXT_PORTNUM = int(portnums_pb2.PortNum.TEXT_MESSAGE_APP) if PROTOBUF_AVAILABLE else TEXT_MESSAGE_APP_PORT
TELEMETRY_PORTNUM = int(portnums_pb2.PortNum.TELEMETRY_APP) if PROTOBUF_AVAILABLE else TELEMETRY_APP_PORT

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
        # The 'from' field is a reserved Python keyword, so protobuf may expose it as 'from_'
        # Try both variants and accept any non-None value (including 0)
        if hasattr(packet, 'from_'):
            fid = packet.from_
        elif hasattr(packet, 'from'):
            fid = getattr(packet, 'from')
    except Exception as e:
        logger.debug(f"Could not extract node ID from packet: {e}")
        fid = None
    
    # Return formatted node ID if we got a valid value (including 0)
    if fid is not None:
        return f"!{fid:08x}"
    return None

def _decode_telemetry_to_sensor_data(payload_bytes):
    """
    Decode Port 67 (TELEMETRY_APP) protobuf payload to sensor_data dict.
    Returns dict with pm1, pm25, pm4, pm10, voc, nox, t, rh or None if not air quality data.
    """
    try:
        telemetry = telemetry_pb2.Telemetry()
        telemetry.ParseFromString(payload_bytes)
        
        # Check if this is air quality telemetry
        if not telemetry.HasField('air_quality_metrics'):
            logger.debug("Telemetry message does not contain air_quality_metrics")
            return None
        
        aq = telemetry.air_quality_metrics
        
        # Map telemetry fields to our sensor_data format
        # Using standard values (not environmental) for PM readings
        sensor_data = {
            'pm1': aq.pm10_standard if aq.pm10_standard > 0 else 0,  # PM1.0
            'pm25': aq.pm25_standard if aq.pm25_standard > 0 else 0,  # PM2.5
            'pm4': aq.pm40_standard if aq.pm40_standard > 0 else 0,  # PM4.0
            'pm10': aq.pm100_standard if aq.pm100_standard > 0 else 0,  # PM10
            'voc': aq.pm_voc_idx if aq.pm_voc_idx > 0 else 0,  # VOC index
            'nox': aq.pm_nox_idx if aq.pm_nox_idx > 0 else 0,  # NOx index
            't': aq.pm_temperature if aq.pm_temperature != 0 else 0,  # Temperature
            'rh': aq.pm_humidity if aq.pm_humidity != 0 else 0  # Humidity
        }
        
        logger.debug(f"Decoded air quality telemetry: PM2.5={sensor_data['pm25']}, PM10={sensor_data['pm10']}")
        return sensor_data
        
    except Exception as e:
        logger.error(f"Error decoding telemetry payload: {e}")
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
                
                logger.debug(f"✓ Parsed protobuf ServiceEnvelope ({len(msg.payload)} bytes)")

                # Extract node ID from packet
                node_id = _get_node_id_from_packet(envelope.packet)
                if not node_id:
                    logger.warning("Could not extract node_id from protobuf packet")
                    return

                # Check if packet has decoded data (not encrypted)
                if not envelope.packet.HasField('decoded'):
                    logger.debug(f"Skipping encrypted packet from {node_id} (no decoded field)")
                    return

                port = envelope.packet.decoded.portnum
                logger.debug(f"Protobuf message from {node_id}, port={port}")

                # Get payload bytes
                payload_bytes = envelope.packet.decoded.payload
                
                if not payload_bytes:
                    logger.debug(f"Empty payload in port {port} message from {node_id}")
                    return
                
                # Process based on port number
                if port == TEXT_PORTNUM:
                    # Port 1: TEXT_MESSAGE_APP - JSON sensor data
                    logger.debug(f"Processing TEXT_MESSAGE_APP (port 1) from {node_id}")
                    
                    try:
                        text_payload = payload_bytes.decode('utf-8', errors='strict')
                    except UnicodeDecodeError as e:
                        logger.warning(f"UTF-8 decode error for port {port} from {node_id}: {e}")
                        return

                    logger.debug(f"Decoded port {port} text from {node_id}: {text_payload[:150]}")
                    
                    # Validate it's JSON sensor data
                    if text_payload.strip().startswith('{'):
                        try:
                            sensor_data = json.loads(text_payload)
                            logger.info(f"✓ Parsed sensor JSON from protobuf port 1 (node {node_id})")
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON in port {port} from {node_id}: {e}")
                            return
                    else:
                        logger.debug(f"Port {port} payload from {node_id} is not JSON: {text_payload[:50]}")
                        return
                
                elif port == TELEMETRY_PORTNUM:
                    # Port 67: TELEMETRY_APP - Binary protobuf with air quality metrics
                    logger.debug(f"Processing TELEMETRY_APP (port 67) from {node_id}")
                    
                    sensor_data = _decode_telemetry_to_sensor_data(payload_bytes)
                    if not sensor_data:
                        logger.debug(f"No air quality data in telemetry from {node_id}")
                        return
                    
                    logger.info(f"✓ Parsed air quality telemetry from protobuf port 67 (node {node_id})")
                
                else:
                    # Other ports - skip
                    logger.debug(f"Skipping unsupported port {port} from {node_id}")
                    return

            except Exception as e:
                logger.error(f"Protobuf decode error: {e}", exc_info=True)
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
