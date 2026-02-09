#!/usr/bin/env python3
"""
Protobuf Message Generator for Testing
Creates sample Meshtastic protobuf messages for testing the MQTT bridge
"""

import sys
import json
from meshtastic.protobuf import mqtt_pb2, mesh_pb2, portnums_pb2

def create_sensor_message(node_id=0xe70287b5, pm25=4.5, pm10=5, temp=24.7, humidity=63.8):
    """Create a protobuf message with sensor data"""
    
    # Create sensor data JSON
    sensor_data = {
        "pm1": 3,
        "pm25": pm25,
        "pm4": 5,
        "pm10": pm10,
        "voc": 103.0,
        "nox": 1.0,
        "t": temp,
        "rh": humidity
    }
    
    # Create protobuf envelope
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
    
    # Set sender and receiver
    setattr(envelope.packet, 'from', node_id)
    envelope.packet.to = 0xffffffff  # broadcast
    
    # Set port to TEXT_MESSAGE_APP
    envelope.packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    
    # Encode sensor data as JSON
    sensor_json = json.dumps(sensor_data)
    envelope.packet.decoded.payload = sensor_json.encode('utf-8')
    
    # Set channel info
    envelope.channel_id = "pulse-aqi"
    envelope.gateway_id = "!gatewaynode"
    
    return envelope

def print_message_info(envelope):
    """Print information about a protobuf message"""
    
    # Extract node ID
    from_id = getattr(envelope.packet, 'from', None)
    if not from_id:
        from_id = getattr(envelope.packet, 'from_', None)
    
    node_id = f"!{from_id:08x}" if from_id is not None else "unknown"
    
    # Get port
    port = envelope.packet.decoded.portnum
    port_name = "UNKNOWN"
    for attr in dir(portnums_pb2.PortNum):
        if not attr.startswith('_') and getattr(portnums_pb2.PortNum, attr) == port:
            port_name = attr
            break
    
    # Decode payload
    payload_text = envelope.packet.decoded.payload.decode('utf-8')
    
    print(f"Node ID:      {node_id}")
    print(f"Channel:      {envelope.channel_id}")
    print(f"Gateway:      {envelope.gateway_id}")
    print(f"Port:         {port} ({port_name})")
    print(f"Payload:      {payload_text}")
    
    # Parse sensor data
    try:
        sensor_data = json.loads(payload_text)
        print(f"\nSensor Data:")
        print(f"  PM2.5:      {sensor_data.get('pm25')} µg/m³")
        print(f"  PM10:       {sensor_data.get('pm10')} µg/m³")
        print(f"  VOC:        {sensor_data.get('voc')}")
        print(f"  NOx:        {sensor_data.get('nox')}")
        print(f"  Temp:       {sensor_data.get('t')}°C")
        print(f"  Humidity:   {sensor_data.get('rh')}%")
    except json.JSONDecodeError:
        print(f"  (Not JSON)")

def save_to_file(envelope, filename):
    """Save protobuf message to a binary file"""
    serialized = envelope.SerializeToString()
    with open(filename, 'wb') as f:
        f.write(serialized)
    print(f"\n✓ Saved {len(serialized)} bytes to {filename}")

def load_from_file(filename):
    """Load protobuf message from a binary file"""
    with open(filename, 'rb') as f:
        data = f.read()
    
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.ParseFromString(data)
    print(f"✓ Loaded {len(data)} bytes from {filename}\n")
    return envelope

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate Meshtastic protobuf test messages')
    parser.add_argument('--node-id', type=lambda x: int(x, 0), default=0xe70287b5,
                        help='Node ID in hex (default: 0xe70287b5)')
    parser.add_argument('--pm25', type=float, default=4.5,
                        help='PM2.5 value (default: 4.5)')
    parser.add_argument('--pm10', type=float, default=5.0,
                        help='PM10 value (default: 5.0)')
    parser.add_argument('--temp', type=float, default=24.7,
                        help='Temperature in Celsius (default: 24.7)')
    parser.add_argument('--humidity', type=float, default=63.8,
                        help='Relative humidity %% (default: 63.8)')
    parser.add_argument('--output', type=str,
                        help='Save to binary file')
    parser.add_argument('--load', type=str,
                        help='Load from binary file')
    parser.add_argument('--hex', action='store_true',
                        help='Print hex dump')
    
    args = parser.parse_args()
    
    if args.load:
        # Load existing message
        envelope = load_from_file(args.load)
    else:
        # Create new message
        envelope = create_sensor_message(
            node_id=args.node_id,
            pm25=args.pm25,
            pm10=args.pm10,
            temp=args.temp,
            humidity=args.humidity
        )
    
    # Print info
    print("=" * 60)
    print("Protobuf Message Details")
    print("=" * 60)
    print_message_info(envelope)
    
    # Serialize
    serialized = envelope.SerializeToString()
    print(f"\nSerialized Size: {len(serialized)} bytes")
    
    # Hex dump
    if args.hex:
        print(f"\nHex Dump:")
        for i in range(0, len(serialized), 16):
            chunk = serialized[i:i+16]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            print(f"  {i:04x}  {hex_str:<48}  {ascii_str}")
    
    # Save to file
    if args.output:
        save_to_file(envelope, args.output)
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
