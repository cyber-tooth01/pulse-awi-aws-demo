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
                
                node_id = f"!{envelope.packet.from_:08x}" if envelope.packet.from_ else None
                
                if envelope.packet.decoded.portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
                    text_payload = envelope.packet.decoded.payload.decode('utf-8')
                    logger.debug(f"Decoded protobuf text from {node_id}: {text_payload[:100]}")
                    
                    if text_payload.strip().startswith('{'):
                        sensor_data = json.loads(text_payload)
                else:
                    logger.debug(f"Skipping non-text portnum: {envelope.packet.decoded.portnum}")
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
